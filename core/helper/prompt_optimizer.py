import json
import re
import threading
import time
from functools import lru_cache, wraps

from config.prompt_config import optimizer_prompt, optimizer_prompt_lite
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.helper.json_extract import safe_load_json, normalize_json_text, strip_code_blocks, extract_balanced_json


def ttl_cache(seconds: int = 1800):
    """轻量 TTL 结果缓存装饰器（线程安全）。

    用法约定：装饰在**实例方法**上，key 由「除 self 外的参数」构成；
    返回值按引用缓存，调用方若需修改请自行拷贝。
    """

    def decorator(func):
        store: dict = {}
        lock = threading.Lock()

        @wraps(func)
        def wrapper(*args, **kwargs):
            # args[0] 为 self：不同实例/不同模型互不串用缓存
            key = (args[0],) + tuple(args[1:]) + tuple(sorted(kwargs.items()))
            now = time.time()
            with lock:
                hit = store.get(key)
                if hit is not None:
                    value, expire_at = hit
                    if now < expire_at:
                        return value
            value = func(*args, **kwargs)
            with lock:
                store[key] = (value, now + seconds)
                # 容量保护：条目过多时优先清理已过期项，避免无界增长
                if len(store) > 1024:
                    for k, (_, expire_at) in list(store.items()):
                        if now >= expire_at:
                            store.pop(k, None)
            return value

        wrapper.cache_clear = lambda: store.clear()  # type: ignore[attr-defined]
        return wrapper

    return decorator


class PromptOptimizer:
    def __init__(self, model):
        self.model = model
        self.valid_topic_set = {
            "Self_Understanding", "Self_Acceptance", "Personal_Growth", "Emotion_Regulation", "Anxiety",
            "Uncertainty", "Perfectionism", "Motivation", "Action", "Learning", "Skill_Development",
            "Career", "Relationships", "Cognitive_Patterns", "Values", "Stress_Health", "Lifestyle",
            "Psychology", "Philosophy", "Happiness"
        }
        # 进程内结果缓存：TTL 30 分钟 + 最多 256 条，命中的 query 直接复用改写结果。
        # 目的：同一 prompt 重复做检索实验时 optimized 稳定可复现（本地 LLM 改写本身是非确定性的），
        # 同时省掉重复的 LLM 调用；TTL 到期或显式 cache_clear() 后重算。
        # 注意：命中缓存的调用不会写 trace（只有真正执行改写的调用才打印「Query优化完成」）。
        # 缓存键包含 want_hyde，所以 lite / 完整两个提示词的结果互不串用。
        cached_once = ttl_cache(seconds=1800)(self._optimize_prompt_uncached)
        self.optimize_prompt = lru_cache(maxsize=256, typed=False)(cached_once)

    def cache_clear(self):
        """显式失效查询改写缓存（模型/主题集合变更后调用）。"""
        self.optimize_prompt.cache_clear()

    def _optimize_prompt_uncached(self, prompt: str, want_hyde: bool = False):
        # 默认走 lite 提示词：不生成 HyDE 长文本（默认链路用不到），单次调用更快；
        # 只有真正启用 HyDE 召回链路时才让模型多写两段假设文档。
        system_content = optimizer_prompt if want_hyde else optimizer_prompt_lite
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt}
        ]
        try:
            raw_resp = self.model.chat(messages=messages).strip()
            data = safe_load_json(raw_resp)
            # 二次尝试：兼容模型输出单引号键（公共清洗不做单引号替换，避免误伤字符串内容）
            if data is None:
                cleaned = normalize_json_text(strip_code_blocks(raw_resp))
                sub = extract_balanced_json(cleaned)
                if sub is not None:
                    try:
                        data = json.loads(sub.replace("'", '"'))
                    except (json.JSONDecodeError, ValueError):
                        data = None
            if data is None:
                raise ValueError("返回内容未包含完整{} JSON结构")

            data["search_query"] = data.get("search_query", prompt)
            data["match_topics"] = data.get("match_topics", [])
            data["keywords"] = data.get("keywords", [])

            data["match_topics"] = [t for t in data["match_topics"] if t in self.valid_topic_set][:3]

            data["keywords"] = self._clean_terms(data["keywords"], min_len=2, max_len=6, limit=4)
            # v2 新增字段：缺失时给空值，调用方按「有则用、无则退化为 v1 行为」处理
            data["distinctive_terms"] = self._clean_terms(
                data.get("distinctive_terms", []), min_len=2, max_len=12, limit=5
            )
            data["hyde_experience"] = self._clean_text(data.get("hyde_experience", ""), 400)
            data["hyde_principle"] = self._clean_text(data.get("hyde_principle", ""), 400)

            return data

        except json.JSONDecodeError as json_err:
            GLOBAL_TRACKER.add_trace(
                stage="optimize_prompt",
                label="Query优化JSON解析失败",
                content={"error": str(json_err)},
                is_error=True,
                error_msg=f"JSON解析失败: {json_err}\n原始输出: {raw_resp[:300]}"
            )
            return self._fallback(prompt)
        except ValueError as val_err:
            GLOBAL_TRACKER.add_trace(
                stage="optimize_prompt",
                label="Query优化JSON结构异常",
                content={"error": str(val_err)},
                is_error=True,
                error_msg=f"JSON结构异常: {val_err}\n原始输出: {raw_resp[:300]}"
            )
            return self._fallback(prompt)
        except Exception as e:
            GLOBAL_TRACKER.add_trace(
                stage="optimize_prompt",
                label="Query优化未知异常",
                content={},
                is_error=True,
                error_msg=str(e)
            )
            return self._fallback(prompt)

    def _fallback(self, prompt: str) -> dict:
        return {
            "search_query": prompt,
            "match_topics": [],
            "keywords": [],
            "distinctive_terms": [],
            "hyde_experience": "",
            "hyde_principle": "",
        }

    @staticmethod
    def _clean_terms(value, min_len: int = 2, max_len: int = 6, limit: int = 4) -> list:
        """清洗 LLM 给出的词项列表：去空、去重、限长、限数量（保序）。"""
        out: list[str] = []
        seen = set()
        if not isinstance(value, (list, tuple)):
            return out
        for item in value:
            if not isinstance(item, str):
                continue
            term = item.strip().strip("，。、,.;；：: ").strip()
            if not (min_len <= len(term) <= max_len) or term in seen:
                continue
            seen.add(term)
            out.append(term)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _clean_text(value, limit: int) -> str:
        """清洗长文本字段：压平空白、限长。"""
        if not isinstance(value, str):
            return ""
        text = re.sub(r"\s+", " ", value).strip()
        return text[:limit]

