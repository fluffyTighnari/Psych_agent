# -*- coding: utf-8 -*-
"""纯函数原语：筛选参数归一 / 会话id生成 / 记忆检索 / prompt 格式化 / 检索 query 分解。"""
import json
from datetime import datetime
from typing import Optional, List, Union

from config.path_config import MEMORY_DIR
from config.prompt_config import decompose_query_prompt
from config.topic_config import search_topic, VALID_TOPICS
from core.schema import Memory
from core.helper import retrieval_config as RC
from core.helper.json_extract import strip_code_blocks
from core.helper.memory_cache import MEMORY_CACHE
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.infra.context import get_app_context


def has_any_filter(*args) -> bool:
    """判断是否存在任意有效筛选条件，全为None返回False"""
    for arg in args:
        if arg is None:
            continue
        if isinstance(arg, (list, tuple)):
            if any(str(x).strip() for x in arg):
                return True
        elif str(arg).strip() != "":
            return True
    return False


def resolve_topics(topic_keyword) -> Optional[List[str]]:
    """主题关键词（单个字符串或列表）→ 标准英文主题标签列表，OR 语义。"""
    if topic_keyword is None:
        return None
    items = [topic_keyword] if isinstance(topic_keyword, str) else list(topic_keyword)
    resolved = []
    for kw in items:
        k = str(kw).strip()
        if not k:
            continue
        if k in VALID_TOPICS:
            resolved.append(k)
        else:
            t = search_topic(k)
            if t:
                resolved.append(t)
    return resolved or None


def to_list(v) -> Optional[List[str]]:
    """兼容单值/多值入参，归一化为非空字符串列表；空返回 None。"""
    if v is None:
        return None
    if isinstance(v, str):
        items = [v]
    elif isinstance(v, (list, tuple)):
        items = list(v)
    else:
        items = [v]
    cleaned = [str(x).strip() for x in items if x is not None and str(x).strip()]
    return cleaned or None


def generate_session_id() -> str:
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    mem_dir = MEMORY_DIR
    if mem_dir.exists():
        existing = [f.stem for f in mem_dir.glob(f"session_{date_str}_*.json")]
        max_n = 0
        for e in existing:
            try:
                n = int(e.rsplit("_", 1)[-1])
                max_n = max(max_n, n)
            except ValueError:
                pass
        seq = max_n + 1
    else:
        seq = 1
    return f"session_{date_str}_{seq:03d}"


def search_related_memories(query: str, top_k: int = 3) -> List[Memory]:
    """Search memory vector DB for similar past sessions. Returns Memory list."""
    embedding_model = get_app_context().memory_embedding()
    vec_db = get_app_context().memory_vector_db()

    if vec_db.count() == 0:
        return []

    emb = embedding_model.encode(query)
    hit_ids = vec_db.query(emb, top_k=top_k)

    if not hit_ids:
        return []

    all_memories = MEMORY_CACHE.memories
    id_to_memory = {m.id: m for m in all_memories}
    results = [id_to_memory[mid] for mid in hit_ids if mid in id_to_memory]
    return results


def _format_memories_for_prompt(memories: List[Memory]) -> str:
    if not memories:
        return "暂无相关历史会话记录"
    blocks = []
    for idx, m in enumerate(memories, 1):
        block = f"【历史会话{idx}】ID:{m.id}\n"
        block += f"主题：{m.title}\n"
        block += f"时间：{m.start_time} ~ {m.end_time}\n"
        block += f"概要：{m.summary}\n"
        if m.insights:
            block += f"核心洞察：{'；'.join(m.insights)}\n"
        if m.keywords:
            block += f"关键词：{', '.join(m.keywords)}\n"
        blocks.append(block)
    return "\n---\n".join(blocks)


def _format_chat_history(chat_history: List[dict]) -> str:
    """格式化当前会话对话历史（本轮之前的 user/assistant 轮次）。"""
    if not chat_history:
        return "暂无当前会话对话历史"
    lines = []
    for msg in chat_history:
        role = "用户" if msg.get("role") == "user" else "咨询师"
        lines.append(f"{role}：{msg.get('content', '')}")
    return "\n".join(lines)


def _format_guided_reasons(guided_reasons: List[dict]) -> str:
    """格式化引导推理问答链 [{role:'guide'|'user', content}] 为文本。"""
    if not guided_reasons:
        return "暂无已完成推理"
    lines = []
    for msg in guided_reasons:
        role = "引导者" if msg.get("role") == "guide" else "用户"
        lines.append(f"{role}：{msg.get('content', '')}")
    return "\n".join(lines)


def format_attached_context(attachments: Optional[List[dict]]) -> str:
    """格式化用户主动引用的资料。

    attachments 来自前端「附上文档 / 追问某条消息」：
      {"kind": "document", "title": "...", "content": "...", "doc_id": "..."}
      {"kind": "message", "role": "guide|advisor", "content": "..."}

    这些是**用户明确要求围绕其回答**的内容，优先级高于检索召回。
    与检索证据分开呈现，避免模型把「用户给的」和「检索到的」混为一谈。
    """
    if not attachments:
        return "无"

    blocks: List[str] = []
    for idx, att in enumerate(attachments, 1):
        if not isinstance(att, dict):
            continue
        kind = str(att.get("kind") or "document")
        title = str(att.get("title") or "").strip()
        content = str(att.get("content") or "").strip()
        if not content:
            continue

        if kind == "message":
            role = "引导者的提问" if att.get("role") == "guide" else "建议者的建议"
            blocks.append(f"【引用{idx}｜{role}】{title}\n{content}")
        else:
            doc_id = str(att.get("doc_id") or "").strip()
            id_part = f"（ID:{doc_id}）" if doc_id else ""
            blocks.append(f"【引用{idx}｜用户笔记《{title}》{id_part}】\n{content}")

    if not blocks:
        return "无"
    return "\n\n---\n\n".join(blocks)


# ===================== 检索 query 分解（阶段 4-C） =====================

_TRIM_CHARS = "，。、,.;；：:！？?! \t\r\n\"'“”‘’【】[]（）()"


def _extract_json_array(text: str) -> Optional[list]:
    """从 LLM 输出中提取第一个完整 JSON 数组（去代码块 + 字符串感知的括号配对）。

    只接受数组；任何解析失败返回 None，由调用方走「不分解」兜底。
    """
    cleaned = strip_code_blocks(text or "")
    start = cleaned.find("[")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(cleaned[start:i + 1])
                except (json.JSONDecodeError, ValueError):
                    return None
                return data if isinstance(data, list) else None
    return None


def decompose_query(problem: str, llm=None,
                    max_queries: int = RC.REMEDIATION_MAX_QUERIES) -> List[str]:
    """把复合/模糊的检索 query 拆成可分别检索的子查询（阶段 4-C CRAG 补救用）。

    返回列表，**第一条恒为原始问题**（保证「分解无增益」时退化为单查询检索）：
    - 问题为空 → []
    - 问题过短（< DECOMPOSE_MIN_CHARS）→ [原问题]
    - LLM 失败 / 输出非数组 / 子查询全部无效 → [原问题]

    约束（避免把「可选参照」变成「无限检索」）：
    - 子查询数量上限由 ``max_queries`` 硬限制（含原查询），默认 3；
    - 只使用用户原话信息，不做主题扩展、不做诊断推断；
    - 子查询之间做包含关系去重，避免同一方面重复检索。

    ``llm`` 需提供 ``chat(messages=[...]) -> str``（与 ``core.llm.LLM`` 一致）；
    不传时用 AppContext 的 small 模型（与意图分类/Query 优化同一槽位）。
    """
    base = (problem or "").strip()
    if not base:
        return []
    # 与检索链路同一口径：情境不参与检索，避免稀释主题
    problem_only = base.split("【具体情境】", 1)[0].strip() or base
    if len(problem_only) < RC.DECOMPOSE_MIN_CHARS:
        return [problem_only]

    if llm is None:
        llm = get_app_context().classify_llm()

    try:
        raw = llm.chat(messages=[
            {"role": "system", "content": decompose_query_prompt},
            {"role": "user", "content": problem_only},
        ])
        items = _extract_json_array(raw) or []
    except Exception as exc:  # noqa: BLE001 - 分解是可选增强，任何失败都退回单查询
        GLOBAL_TRACKER.add_trace(
            stage="decompose_query",
            label="查询分解失败，退回单查询检索",
            content={"error": str(exc)[:160]},
            is_error=True,
            error_msg=str(exc)[:300],
        )
        return [problem_only]

    subs: List[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        q = item.strip().strip(_TRIM_CHARS)
        if not (RC.DECOMPOSE_MIN_CHARS <= len(q) <= RC.DECOMPOSE_MAX_SUB_CHARS):
            continue
        if q == problem_only:
            continue
        # 包含关系去重：同一方面的长短写法只保留先出现的
        if any(q in seen or seen in q for seen in subs):
            continue
        subs.append(q)
        if len(subs) >= max_queries - 1:
            break

    result = [problem_only] + subs
    GLOBAL_TRACKER.add_trace(
        stage="decompose_query",
        label="查询分解完成",
        content={"raw_len": len(problem_only), "queries": result, "sub_count": len(subs)},
    )
    return result



