"""可配置检索调试流水线（契约：docs/retrieval_debug_contract.md §1 / §2）。

对外提供：
- ``get_retrieval_components()`` 进程级单例 + ``threading.Lock`` 懒加载，首次调用才装载本地模型
  （embedding / reranker），import 期不加载任何模型；失败时向上抛异常，由 API 层兜底。
- ``RetrievalPipeline.run()`` 按勾选组合 dense / bm25 / rrf / rerank 执行检索，返回纯 JSON 可
  序列化的 ``{"stages", "final", "logs", ...}``。
- ``run_pipeline()`` 模块级便捷函数，内部用 ``get_retrieval_components()`` 组装。

实现说明 / 取舍（v2 优化版，调优依据见 docs/rag_optimization_report.md）：

1. **dense 检索文本 = 多向量加权平均**：把「原始提问」「LLM 改写问句」分别编码后按
   ``DENSE_QUERY_WEIGHTS``（默认 query:1.0 / search_query:0.5）加权平均并重新归一化。
   不再把两段文本直接字符串拼接（旧实现 ``search_query + query`` 无分隔符，且无法调权重）。
   可选第 3 条链路：HyDE 假设文档（``use_hyde=True``）。
2. **BM25 token = 加权词项序列**：原话与 ``distinctive_terms`` 高权重、topics/keywords 低权重
   （``BM25_QUERY_WEIGHTS``），用词项重复次数表达权重（BM25 对 query 词频是线性的）。
   这直接对症「扩展词稀释原始意图 / 让候选文档获得虚假匹配优势」。
3. **BM25 索引本身是富索引**：索引文档 = 标题 + 摘要 + 关键词 + 主题 + 周记三段 + 正文
   （见 ``core/helper/BM25.py`` 与 ``core/helper/retrieval_config.py``），使词频差异与长度
   归一化都作用在真实文本上。**改索引规格后必须重建 ``store/bm25_store/bm25``**。
4. **RRF 为加权倒数排名融合**：``w / (pos + k)``，k 默认 3（远小于旧值 60）。k 太大时
   ``1/(pos+k)`` 几乎与排名无关，融合退化为「无序并集」。权重与 k 的消融见报告。
5. **重排候选池（rerank_pool）**：融合排序后先截断到前 N 再送 cross-encoder，默认 10。
   这样 RRF 的排序在「开启重排」时依然起作用（旧实现重排会丢弃 RRF 顺序，RRF 只贡献并集）。
6. **dense 分数 = Chroma 的 L2 距离**（越小越相似），故 dense 阶段 score 比其他阶段小；
   顺序即 Chroma 返回顺序（已按距离升序），rank 从 1 开始。
7. **rerank 真实分数**：``rerank_documents`` 只返回 Document 不返回分数，因此额外用
   ``pipeline.reranker.model.predict(pairs)`` 复算一遍，pairs 构造规则与 reranker 内部
   ``build_input_text`` 完全一致（两者都走 ``core/helper/retrieval_text.rerank_input_text``）。
8. **结果里的 ``doc``**：填充契约 §2.4 的 DOC_VIEW 形状 dict（JSON 安全）。
9. **阶段语义**（契约 §2.3）：rrf / rerank 需要候选来源，若 dense 与 bm25 都未勾选（只勾 rrf 或
   只勾 rerank），默认启用双路召回；dense 与 bm25 同时启用时（即使没勾 rrf）也必须融合。
   全不勾 / 空 query → ``ValueError("至少选择一种检索方式")``。
10. **Document 加载兜底**：主路径严格用 ``knowledge_loader.load_knowledge(ids)``；若某 id 未解析出
    Document（典型场景：``config/id_map.json`` 里存的是其他机器的绝对路径），则回退到
    §1 列出的 ``KNOWLEDGE_CACHE`` 补齐，两者都取不到才计入 missing 并写日志。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from config.path_config import BM25_PATH, COLLECTION_NAME, VECTOR_DB_DIR
from core.helper import retrieval_config as RC
from core.helper.retrieval_text import (
    bm25_query_tokens,
    dense_query_texts,
    rerank_input_text,
)
from core.helper.trace_tracker import TraceTracker

# 阶段 → 中文标签（契约 §2.2 / 前端展示）
PIPELINE_STAGE_LABELS: Dict[str, str] = {
    "optimize_prompt": "Query 优化",
    "dense": "向量召回(Dense)",
    "bm25": "BM25 关键词召回",
    "hyde": "HyDE 假设文档召回",
    "rrf": "RRF 融合",
    "rerank": "Cross-Encoder 重排",
}

# 阶段固定顺序（契约 §2.2；hyde 为 v2 新增的可选链路，排在 rrf 之前）
PIPELINE_STAGE_ORDER: Tuple[str, ...] = (
    "optimize_prompt",
    "dense",
    "bm25",
    "hyde",
    "rrf",
    "rerank",
)

# ===================== 进程级组件单例（懒加载 + 线程安全） =====================

_COMPONENTS: Optional[Dict[str, Any]] = None
_COMPONENTS_LOCK = threading.Lock()


def get_retrieval_components() -> dict:
    """返回 ``{'embedding_model','vector_db','bm25','prompt_optimizer','knowledge_loader','reranker'}``。

    首次调用才装载本地模型（embedding 约 1s、reranker 约 4s）；后续调用直接复用同一批实例。
    装载失败时向上抛异常（由 API 层兜底），且不缓存半成品，下一次调用可重试。
    """
    global _COMPONENTS
    if _COMPONENTS is None:
        with _COMPONENTS_LOCK:
            if _COMPONENTS is None:
                _COMPONENTS = _build_retrieval_components()
    return _COMPONENTS


def invalidate_retrieval_components() -> None:
    """清空进程级组件单例（换模型 / 换 embedding 后调用）；下次 get_retrieval_components() 重新装载。"""
    global _COMPONENTS
    with _COMPONENTS_LOCK:
        _COMPONENTS = None


def _build_retrieval_components() -> Dict[str, Any]:
    """真正构造组件；所有重依赖都在函数内 import，避免 import 期加载模型/建向量库连接。"""
    from config.model_config import EMBEDDING_MODEL, GLOBAL_MODEL, RERANKING_MODEL
    from core.embedding.embedding import EmbeddingModel
    from core.helper.BM25 import BM25TagIndexer
    from core.helper.prompt_optimizer import PromptOptimizer
    from core.helper.reranker import Reranker
    from core.llm import LLM
    from core.loader.knowledge_loader import KnowledgeLoader
    from core.vector_db.documents_vector_db import VectorDB

    # 先构造轻量组件，再装载重模型；任一环节失败都不会污染单例
    vector_db = VectorDB(VECTOR_DB_DIR, COLLECTION_NAME)
    # 纯检索场景 documents=[]：直接加载本地已有索引（索引内的 k1/b 已被烘焙，读取时同步）
    bm25 = BM25TagIndexer(
        documents=[],
        bm25_path=BM25_PATH,
    )
    prompt_optimizer = PromptOptimizer(LLM(GLOBAL_MODEL.small))
    knowledge_loader = KnowledgeLoader()
    embedding_model = EmbeddingModel(EMBEDDING_MODEL)
    reranker = Reranker(RERANKING_MODEL)

    return {
        "embedding_model": embedding_model,
        "vector_db": vector_db,
        "bm25": bm25,
        "prompt_optimizer": prompt_optimizer,
        "knowledge_loader": knowledge_loader,
        "reranker": reranker,
    }


# ===================== 序列化工具 =====================


def _round_score(value: Any) -> float:
    """分数统一四舍五入到 6 位，且强制转成 Python float（杜绝 numpy 标量进入返回值）。"""
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


def _round_ms(value: Any) -> float:
    """耗时统一保留 1 位小数。"""
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return 0.0


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


def _as_opt_str(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_float_array(vec: Any):
    """把 embedding 输出统一转成 float32 numpy 数组（支持 list / np.ndarray / torch.Tensor）。"""
    import numpy as np

    if hasattr(vec, "detach"):  # torch.Tensor
        vec = vec.detach().cpu().numpy()
    arr = np.asarray(vec, dtype="float32").reshape(-1)
    return arr


def _doc_view(doc: Any) -> Optional[dict]:
    """把 Document 转成契约 §2.4 的 DOC_VIEW（纯 JSON 可序列化）；doc 为 None 时原样返回 None。"""
    if doc is None:
        return None
    return {
        "doc_id": _as_str(getattr(doc, "doc_id", "")),
        "title": _as_str(getattr(doc, "title", "")),
        "doc_type": _as_str(getattr(doc, "doc_type", "")),
        "date": _as_str(getattr(doc, "date", "")),
        "source": _as_str(getattr(doc, "source", "")),
        "relative_path": _as_str(getattr(doc, "relative_path", "")),
        "knowledge_path": _as_str(getattr(doc, "knowledge_path", "")),
        "summary": _as_str(getattr(doc, "summary", "")),
        "topic": _as_str_list(getattr(doc, "topic", None)),
        "keywords": _as_str_list(getattr(doc, "keywords", None)),
        "emotion": dict(getattr(doc, "emotion", None) or {}) if isinstance(getattr(doc, "emotion", None), dict) else {},
        "problem": _as_opt_str(getattr(doc, "problem", None)),
        "analysis": _as_opt_str(getattr(doc, "analysis", None)),
        "solution": _as_opt_str(getattr(doc, "solution", None)),
        "word_count": _as_int(getattr(doc, "word_count", 0), 0),
        "content": _as_str(getattr(doc, "content", "")),
    }


def _add_trace(
    trace: Optional[TraceTracker],
    stage: str,
    label: str,
    content: dict,
    is_error: bool = False,
    error_msg: Optional[str] = None,
) -> None:
    """trace 为 None 时静默跳过；content 必须是 JSON 可序列化的纯 Python 结构。"""
    if trace is None:
        return
    trace.add_trace(
        stage=stage,
        label=label,
        content=content,
        is_error=is_error,
        error_msg=error_msg,
    )


# ===================== 流水线 =====================


class RetrievalPipeline:
    """可配置检索调试流水线（组件由调用方注入，便于复用与单测）。"""

    def __init__(
        self,
        embedding_model,
        vector_db,
        bm25,
        prompt_optimizer,
        knowledge_loader,
        reranker,
    ):
        self.embedding_model = embedding_model
        self.vector_db = vector_db
        self.bm25 = bm25
        self.prompt_optimizer = prompt_optimizer
        self.knowledge_loader = knowledge_loader
        self.reranker = reranker

    # ---------- 输入准备 / 各阶段实现 ----------

    def _optimize_query(self, query: str, trace: Optional[TraceTracker],
                        want_hyde: bool = False) -> Tuple[dict, float]:
        """阶段 1：Query 优化（任一阶段启用即执行），返回 (info, latency_ms)。"""
        started = time.perf_counter()
        # want_hyde 用于切换提示词：默认 lite（不生成 HyDE 长文本），启用 HyDE 链路时才要完整版。
        # 用 try/except 兼容外部注入的自定义 optimizer（如验证脚本的 StubOptimizer，只接受 query）。
        try:
            raw = self.prompt_optimizer.optimize_prompt(query, want_hyde=want_hyde)
        except TypeError:
            raw = self.prompt_optimizer.optimize_prompt(query)
        latency_ms = (time.perf_counter() - started) * 1000.0

        data = dict(raw) if isinstance(raw, dict) else {}
        info = {
            "search_query": _as_str(data.get("search_query") or query),
            "match_topics": _as_str_list(data.get("match_topics")),
            "keywords": _as_str_list(data.get("keywords")),
            # v2 新增：高区分度词 + 两篇 HyDE 假设文档（经历式 / 原则式）
            "distinctive_terms": _as_str_list(data.get("distinctive_terms")),
            "hyde_experience": _as_str(data.get("hyde_experience")),
            "hyde_principle": _as_str(data.get("hyde_principle")),
        }
        _add_trace(
            trace,
            "optimize_prompt",
            "Query 优化完成",
            {
                "raw_query": query[:120],
                "search_query": info["search_query"][:200],
                "match_topics": info["match_topics"],
                "keywords": info["keywords"],
                "distinctive_terms": info["distinctive_terms"],
                "hyde_chars": [len(info["hyde_experience"]), len(info["hyde_principle"])],
                "latency_ms": _round_ms(latency_ms),
            },
        )
        return info, latency_ms

    def _run_dense(
        self,
        query: str,
        info: dict,
        raw_top_k: int,
        *,
        use_hyde: bool = RC.DEFAULT_USE_HYDE,
        query_weights: Optional[dict] = None,
    ) -> Tuple[List[str], List[float], float, List[dict]]:
        """dense 召回：多向量加权平均编码 → Chroma 查询，score 为 L2 距离（越小越好）。

        返回 (ids, distances, latency_ms, 参与编码的文本明细)。
        """
        started = time.perf_counter()
        parts = dense_query_texts(query, info, use_hyde=use_hyde, weights=query_weights)
        if not parts:
            parts = [(query, 1.0)]

        acc = None
        used: List[dict] = []
        for text, weight in parts:
            vec = self.embedding_model.encode(text)
            vec = _as_float_array(vec) * float(weight)
            acc = vec if acc is None else acc + vec
            used.append({"text": text[:80], "weight": float(weight)})

        norm = float((acc * acc).sum()) ** 0.5
        if norm > 0:
            acc = acc / norm
        result = self.vector_db.query(acc, raw_top_k)

        ids = list((result.get("ids") or [[]])[0] or [])
        distances = list((result.get("distances") or [[]])[0] or [])
        scores = [_round_score(d) for d in distances[: len(ids)]]
        if len(scores) < len(ids):
            # 理论上不会发生；兜底避免 rank 与 score 长度错位
            scores.extend([0.0] * (len(ids) - len(scores)))
        latency_ms = (time.perf_counter() - started) * 1000.0
        return [str(i) for i in ids], scores, latency_ms, used

    def _run_bm25(
        self,
        query: str,
        info: dict,
        raw_top_k: int,
        *,
        query_weights: Optional[dict] = None,
    ) -> Tuple[List[str], List[float], float, str, List[str]]:
        """BM25 召回：加权词项序列 → 分数降序取 top raw_top_k。

        返回 (ids, scores, ms, score_mode, tokens)。
        """
        started = time.perf_counter()
        tokens = bm25_query_tokens(query, info, query_weights)

        bm25_model = getattr(self.bm25, "bm25", None)
        doc_id_list = list(getattr(self.bm25, "doc_id_list", None) or [])

        if bm25_model is not None and hasattr(bm25_model, "get_scores") and doc_id_list:
            # 与 BM25TagIndexer.search() 相同的排序 / 过滤语义：分数降序、过滤 0 分、取 top raw_top_k
            raw_scores = bm25_model.get_scores(tokens)
            ranked = sorted(range(len(raw_scores)), key=lambda idx: float(raw_scores[idx]), reverse=True)
            ids: List[str] = []
            scores: List[float] = []
            for idx in ranked:
                score = float(raw_scores[idx])
                if score > 0 and len(ids) < raw_top_k:
                    ids.append(str(doc_id_list[idx]))
                    scores.append(_round_score(score))
            score_mode = "bm25_raw"
        else:
            # 回退：拿不到原始分数时用 search() 的排名倒数作为占位分数
            hit_ids = list(self.bm25.search(tokens, raw_top_k) or [])
            ids = [str(i) for i in hit_ids]
            scores = [_round_score(1.0 / (pos + 1)) for pos in range(len(ids))]
            score_mode = "reciprocal_rank"

        latency_ms = (time.perf_counter() - started) * 1000.0
        return ids, scores, latency_ms, score_mode, tokens

    def _rrf_fuse(
        self,
        dense_ids: List[str],
        bm25_ids: List[str],
        rrf_k: int,
        w_dense: float = RC.DEFAULT_W_DENSE,
        w_bm25: float = RC.DEFAULT_W_BM25,
        hyde_ids: Optional[List[str]] = None,
        w_hyde: float = 0.0,
    ) -> Tuple[List[str], List[float]]:
        """加权倒数排名融合：``score += w / (pos + rrf_k)``（pos 从 0 开始）。

        rrf_k 是「排名折扣强度」：k 越小，排名靠前的候选优势越明显；
        k 很大（如旧默认 60）时 1/(pos+k) 几乎与 pos 无关，融合退化为无序并集。
        """
        rank_score: Dict[str, float] = {}
        for lst, weight in ((dense_ids, w_dense), (bm25_ids, w_bm25), (hyde_ids or [], w_hyde)):
            if not weight:
                continue
            for pos, doc_id in enumerate(lst):
                rank_score[doc_id] = rank_score.get(doc_id, 0.0) + float(weight) / (pos + rrf_k)
        sorted_items = sorted(rank_score.items(), key=lambda item: item[1], reverse=True)
        return [doc_id for doc_id, _ in sorted_items], [_round_score(score) for _, score in sorted_items]

    def _load_documents(self, ids: List[str]) -> Tuple[Dict[str, Any], List[str]]:
        """批量加载 Document，返回 (doc_id -> Document, 缺失 id 列表)。顺序与入参顺序一致。

        主路径按契约走 ``knowledge_loader.load_knowledge(ids)``；若某 id 未解析出 Document
        （典型场景：``config/id_map.json`` 里存的是其他机器的绝对路径，跨平台迁移后失效），
        则用契约 §1 列出的 ``KNOWLEDGE_CACHE``（同样按 JSON 的 id 建索引）兜底同一批文档。
        两种情况都取不到时才计入 missing。
        """
        ordered: List[str] = []
        seen = set()
        for item in ids:
            key = str(item)
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)

        known = getattr(self.knowledge_loader, "data", None)
        candidates = [key for key in ordered if key in known] if isinstance(known, dict) else list(ordered)

        doc_map: Dict[str, Any] = {}
        if candidates:
            for doc in self.knowledge_loader.load_knowledge(candidates) or []:
                doc_map[str(getattr(doc, "doc_id", ""))] = doc

        unresolved = [key for key in ordered if key not in doc_map]
        if unresolved:
            # 函数内 import：避免 import 期扫描知识库目录
            from core.helper.knowledge_cache import KNOWLEDGE_CACHE

            cache = getattr(KNOWLEDGE_CACHE, "cache", None)
            if isinstance(cache, dict):
                for key in unresolved:
                    doc = cache.get(key)
                    if doc is not None:
                        doc_map[key] = doc

        missing = [key for key in ordered if key not in doc_map]
        return doc_map, missing

    @staticmethod
    def _build_rerank_input(doc, variant: Optional[str] = None) -> str:
        """与 reranker.build_input_text 完全一致（两者共用 core/helper/retrieval_text 的实现）。"""
        return rerank_input_text(doc, variant or RC.RERANK_INPUT_VARIANT)

    def _cross_encoder_scores(self, query: str, docs: List[Any],
                              variant: Optional[str] = None) -> List[Tuple[Any, float]]:
        """用 cross-encoder 复算分数（reranker 不返回分数），按分数降序、稳定排序（同分保持输入顺序）。"""
        pairs = [(query, self._build_rerank_input(doc, variant)) for doc in docs]
        raw_scores = self.reranker.model.predict(pairs)
        scored = [(doc, _round_score(score)) for doc, score in zip(docs, raw_scores)]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored

    # ---------- 结果组装 ----------

    @staticmethod
    def _make_results(ids: List[str], scores: List[float], doc_map: Optional[Dict[str, Any]] = None) -> List[dict]:
        results: List[dict] = []
        for pos, doc_id in enumerate(ids):
            key = str(doc_id)
            score = scores[pos] if pos < len(scores) else 0.0
            doc = doc_map.get(key) if doc_map else None
            results.append(
                {
                    "doc_id": key,
                    "rank": pos + 1,
                    "score": _round_score(score),
                    "doc": _doc_view(doc),
                }
            )
        return results

    @staticmethod
    def _make_stage(name: str, latency_ms: float, results: List[dict], extra: Optional[dict] = None) -> dict:
        stage = {
            "name": name,
            "label": PIPELINE_STAGE_LABELS.get(name, name),
            "enabled": True,
            "latency_ms": _round_ms(latency_ms),
            "output_count": len(results),
            "results": results,
        }
        if extra is not None:
            stage["extra"] = extra
        return stage

    @staticmethod
    def _pairs_to_results(pairs: List[Tuple[Any, float]]) -> List[dict]:
        results: List[dict] = []
        for pos, (doc, score) in enumerate(pairs):
            results.append(
                {
                    "doc_id": str(getattr(doc, "doc_id", "")),
                    "rank": pos + 1,
                    "score": _round_score(score),
                    "doc": _doc_view(doc),
                }
            )
        return results

    # ---------- 主入口 ----------

    def run(
        self,
        query: str,
        *,
        dense: bool = True,
        bm25: bool = True,
        rrf: bool = True,
        rerank: bool = True,
        raw_top_k: int = RC.DEFAULT_RAW_TOP_K,
        final_top_k: int = RC.DEFAULT_FINAL_TOP_K,
        rrf_k: int = RC.DEFAULT_RRF_K,
        score_threshold: Optional[float] = None,
        trace: Optional[TraceTracker] = None,
        # ---- v2 新增可调项（默认值即调优后的最优配置）----
        w_dense: float = RC.DEFAULT_W_DENSE,
        w_bm25: float = RC.DEFAULT_W_BM25,
        bm25_query_weights: Optional[dict] = None,
        dense_query_weights: Optional[dict] = None,
        use_hyde: bool = RC.DEFAULT_USE_HYDE,
        rerank_input: Optional[str] = None,
        rerank_query: str = RC.RERANK_QUERY,
        rerank_pool: int = RC.DEFAULT_RERANK_POOL,
        rerank_mode: str = RC.DEFAULT_RERANK_MODE,
        blend_alpha: float = RC.DEFAULT_BLEND_ALPHA,
    ) -> dict:
        """执行可配置检索流水线，返回纯 JSON 可序列化 dict（契约 §2.2）。

        v2 新增参数：
        - ``w_dense`` / ``w_bm25``：加权 RRF 的两路权重
        - ``bm25_query_weights``：BM25 查询词项权重（键 query/distinctive/search_query/keywords/topics）
        - ``dense_query_weights``：dense 多向量混合权重（键 query/search_query/hyde_experience/hyde_principle）
        - ``use_hyde``：是否启用 HyDE 假设文档的独立召回链路
        - ``rerank_input``：cross-encoder 文档侧文本规格（legacy/with_kw/problem_solution/full）
        - ``rerank_query``：传给 cross-encoder 的查询侧文本（raw=原始提问 / search=改写问句 / both）
        - ``rerank_pool``：先按融合排名截断到前 N 再重排；0 表示不截断
        - ``rerank_mode``：blend（默认，融合排名分 + alpha×重排分）/ filter（仅置信闸门）/ sort（v1 行为）
        - ``blend_alpha``：blend 模式下 cross-encoder 分数的权重

        关于 ``score_threshold``：默认 None 表示用配置默认值 ``RC.DEFAULT_SCORE_THRESHOLD``（0.0，
        即不做硬过滤）。v1 的 0.08 硬阈值会大量截断有效候选（见优化报告）。
        """
        raw_query = (query or "").strip()
        if not raw_query or not any((dense, bm25, rrf, rerank)):
            # 契约 §2.3 规则 5：空输入 / 全不勾
            raise ValueError("至少选择一种检索方式")

        raw_top_k = max(1, _as_int(raw_top_k, RC.DEFAULT_RAW_TOP_K))
        final_top_k = max(1, _as_int(final_top_k, RC.DEFAULT_FINAL_TOP_K))
        rrf_k = max(1, _as_int(rrf_k, RC.DEFAULT_RRF_K))
        w_dense = _as_float(w_dense, RC.DEFAULT_W_DENSE)
        w_bm25 = _as_float(w_bm25, RC.DEFAULT_W_BM25)
        rerank_pool = max(0, _as_int(rerank_pool, RC.DEFAULT_RERANK_POOL))
        blend_alpha = _as_float(blend_alpha, RC.DEFAULT_BLEND_ALPHA)
        rerank_mode = rerank_mode if rerank_mode in RC.RERANK_MODES else RC.DEFAULT_RERANK_MODE

        use_dense = bool(dense)
        use_bm25 = bool(bm25)
        if not use_dense and not use_bm25:
            # 只勾 rrf / 只勾 rerank 时没有显式召回链路，默认双路（契约 §2.3 行 3/4）
            use_dense = True
            use_bm25 = True
        do_rerank = bool(rerank)
        do_rrf = bool(rrf) or (use_dense and use_bm25)

        # ---- 阶段 1：Query 优化 ----
        optimized, opt_latency = self._optimize_query(raw_query, trace, want_hyde=bool(use_hyde))

        # ---- 阶段 2/3：dense 与 bm25（同时启用时并发，stages 顺序固定 dense 在前） ----
        dense_ids: List[str] = []
        dense_scores: List[float] = []
        dense_latency = 0.0
        dense_texts: List[dict] = []
        bm25_ids: List[str] = []
        bm25_scores: List[float] = []
        bm25_latency = 0.0
        bm25_score_mode = "bm25_raw"
        bm25_tokens_used: List[str] = []
        hyde_ids: List[str] = []
        hyde_scores: List[float] = []
        hyde_latency = 0.0

        if use_dense and use_bm25:
            outcome: Dict[str, Any] = {}
            errors: Dict[str, BaseException] = {}

            def _dense_job():
                try:
                    outcome["dense"] = self._run_dense(
                        raw_query, optimized, raw_top_k,
                        use_hyde=False, query_weights=dense_query_weights,
                    )
                except BaseException as exc:  # noqa: BLE001 - 原样抛回主线程
                    errors["dense"] = exc

            def _bm25_job():
                try:
                    outcome["bm25"] = self._run_bm25(
                        raw_query, optimized, raw_top_k, query_weights=bm25_query_weights
                    )
                except BaseException as exc:  # noqa: BLE001
                    errors["bm25"] = exc

            thread_dense = threading.Thread(target=_dense_job, name="retrieval-pipeline-dense", daemon=True)
            thread_bm25 = threading.Thread(target=_bm25_job, name="retrieval-pipeline-bm25", daemon=True)
            thread_dense.start()
            thread_bm25.start()
            thread_dense.join()
            thread_bm25.join()

            # 阶段内部异常不吞掉：按阶段顺序抛第一个
            for name in ("dense", "bm25"):
                if name in errors:
                    raise errors[name]

            dense_ids, dense_scores, dense_latency, dense_texts = outcome["dense"]
            bm25_ids, bm25_scores, bm25_latency, bm25_score_mode, bm25_tokens_used = outcome["bm25"]
        elif use_dense:
            dense_ids, dense_scores, dense_latency, dense_texts = self._run_dense(
                raw_query, optimized, raw_top_k, use_hyde=False, query_weights=dense_query_weights
            )
        elif use_bm25:
            bm25_ids, bm25_scores, bm25_latency, bm25_score_mode, bm25_tokens_used = self._run_bm25(
                raw_query, optimized, raw_top_k, query_weights=bm25_query_weights
            )

        # 可选第三条链路：HyDE 假设文档独立召回（不与主查询向量混合，避免稀释原始意图）
        if use_hyde and use_dense:
            hyde_weights = dense_query_weights or {
                "query": 0.0, "search_query": 0.0,
                "hyde_experience": 1.0, "hyde_principle": 1.0,
            }
            hyde_ids, hyde_scores, hyde_latency, _ = self._run_dense(
                raw_query, optimized, raw_top_k, use_hyde=True, query_weights=hyde_weights
            )

        if use_dense:
            dense_extra = {
                "encoded_texts": dense_texts,
                "score_metric": "l2_distance",
            }
            _add_trace(
                trace,
                "dense",
                "稠密向量检索完成",
                {
                    "encoded_texts": dense_texts,
                    "top_k": raw_top_k,
                    "hit_ids": dense_ids,
                    "distances": dense_scores,
                    "score_metric": "l2_distance",
                    "latency_ms": _round_ms(dense_latency),
                },
            )
        if use_bm25:
            bm25_extra = {
                "token_count": len(bm25_tokens_used),
                "score_mode": bm25_score_mode,
                "match_topics": optimized["match_topics"],
                "keywords": optimized["keywords"],
                "distinctive_terms": optimized.get("distinctive_terms"),
            }
            _add_trace(
                trace,
                "bm25",
                "BM25 稀疏检索完成",
                {
                    "query": raw_query[:120],
                    "match_topics": optimized["match_topics"],
                    "keywords": optimized["keywords"],
                    "distinctive_terms": optimized.get("distinctive_terms"),
                    "token_count": len(bm25_tokens_used),
                    "top_k": raw_top_k,
                    "hit_ids": bm25_ids,
                    "scores": bm25_scores,
                    "score_mode": bm25_score_mode,
                    "latency_ms": _round_ms(bm25_latency),
                },
            )

        # ---- 阶段 4：RRF 融合 ----
        rrf_ids: List[str] = []
        rrf_scores: List[float] = []
        rrf_latency = 0.0
        if do_rrf:
            started = time.perf_counter()
            rrf_ids, rrf_scores = self._rrf_fuse(
                dense_ids, bm25_ids, rrf_k,
                w_dense=w_dense, w_bm25=w_bm25,
                hyde_ids=hyde_ids, w_hyde=(1.0 if hyde_ids else 0.0),
            )
            rrf_latency = (time.perf_counter() - started) * 1000.0
            rrf_extra = {
                "rrf_k": rrf_k,
                "w_dense": _round_score(w_dense),
                "w_bm25": _round_score(w_bm25),
                "hyde_enabled": bool(hyde_ids),
                "dense_count": len(dense_ids),
                "bm25_count": len(bm25_ids),
                "fused_count": len(rrf_ids),
            }
            _add_trace(
                trace,
                "rrf",
                "RRF 融合完成",
                dict(rrf_extra, fused_ids=rrf_ids, top_scores=rrf_scores[:10],
                     latency_ms=_round_ms(rrf_latency)),
            )

        # ---- 加载 Document（供各阶段展示与 rerank 输入） ----
        upstream_ids: List[str] = rrf_ids if do_rrf else (dense_ids if use_dense else bm25_ids)
        all_ids = list(dense_ids) + list(bm25_ids) + list(hyde_ids) + list(rrf_ids) + list(upstream_ids)
        doc_map, missing_ids = self._load_documents(all_ids)
        if missing_ids:
            _add_trace(
                trace,
                "optimize_prompt",
                "候选 doc_id 在本地知识库中不存在，已跳过",
                {"missing_ids": missing_ids},
            )

        # ---- 阶段 5：rerank ----
        final_source = "rrf" if do_rrf else ("dense" if use_dense else "bm25")
        final_pairs: List[Tuple[Any, float]] = []
        rerank_results: List[dict] = []
        rerank_latency = 0.0
        rerank_threshold = 0.0

        if do_rerank:
            # 候选池截断：按融合排名先取前 rerank_pool 篇（0 = 全部），让 RRF 的排序在
            # 「开启重排」时依然参与决策，同时降低 cross-encoder 的推理开销。
            pool_ids = upstream_ids[:rerank_pool] if rerank_pool else list(upstream_ids)
            upstream_docs = [doc_map[key] for key in pool_ids if key in doc_map]
            rerank_query_text = {
                "raw": raw_query,
                "search": optimized["search_query"] or raw_query,
                "both": f"{raw_query} {optimized['search_query'] or ''}".strip(),
            }.get(rerank_query, raw_query)
            started = time.perf_counter()
            # 阈值语义：score_threshold=None 时用配置默认值（0.0 = 不做硬过滤）
            default_threshold = (RC.DEFAULT_SCORE_THRESHOLD if score_threshold is None
                                 else float(score_threshold))
            rerank_threshold = float(default_threshold)
            # 只跑一次交叉编码器（pairs 与 reranker.build_input_text 完全同源），
            # 三种模式都基于同一份分数，避免重复推理。
            scored_pairs = self._cross_encoder_scores(rerank_query_text, upstream_docs, rerank_input)
            rerank_latency = (time.perf_counter() - started) * 1000.0

            # 融合排名归一化分：候选池内第 i 名得 1 - i/len(pool)
            pool_size = max(len(pool_ids), 1)
            rrf_norm = {key: 1.0 - (pos / pool_size) for pos, key in enumerate(pool_ids)}
            score_lookup = {str(getattr(doc, "doc_id", "")): score for doc, score in scored_pairs}
            gated_pairs = [(doc, score) for doc, score in scored_pairs if score >= rerank_threshold]

            authoritative_docs: List[Any] = []
            if rerank_mode == "filter":
                # 只把 cross-encoder 当置信闸门：不改变融合排名，只丢弃低置信候选
                ordered = [doc for doc, _ in gated_pairs]
                stage_pairs = [(doc, score_lookup.get(str(getattr(doc, "doc_id", "")), 0.0))
                               for doc in ordered]
                final_pairs = stage_pairs[:final_top_k]
            elif rerank_mode == "sort":
                # v1 行为：完全由 cross-encoder 决定排序与阈值过滤（此处才需要调用 rerank_documents）
                authoritative_docs = self.reranker.rerank_documents(
                    rerank_query_text, upstream_docs, final_top_k, rerank_threshold
                )
                if authoritative_docs:
                    final_pairs = [(doc, score_lookup.get(str(getattr(doc, "doc_id", "")), 0.0))
                                   for doc in authoritative_docs]
                else:
                    final_pairs = gated_pairs[:final_top_k]
                stage_pairs = final_pairs
            else:
                # blend：融合排名分 + alpha × cross-encoder 概率，二者量纲独立、无需阈值
                blended = []
                for doc, score in scored_pairs:
                    key = str(getattr(doc, "doc_id", ""))
                    blended.append((doc, score, rrf_norm.get(key, 0.0) + blend_alpha * score))
                blended.sort(key=lambda item: item[2], reverse=True)
                if rerank_threshold > 0:
                    blended = [item for item in blended if item[1] >= rerank_threshold]
                final_pairs = [(doc, score) for doc, score, _ in blended[:final_top_k]]
                stage_pairs = [(doc, score) for doc, score, _ in blended]

            rerank_extra = {
                "mode": rerank_mode,
                "blend_alpha": _round_score(blend_alpha),
                "threshold": _round_score(rerank_threshold),
                "rerank_pool": rerank_pool,
                "input_count": len(upstream_docs),
                "before_count": len(scored_pairs),
                "after_count": len(gated_pairs),
                "final_ids": [str(getattr(doc, "doc_id", "")) for doc, _ in final_pairs],
                "doc_with_score": [
                    {"doc_id": str(getattr(doc, "doc_id", "")), "score": _round_score(score)}
                    for doc, score in scored_pairs
                ],
            }
            _add_trace(
                trace,
                "rerank",
                "Cross-Encoder 重排完成",
                dict(rerank_extra, authoritative_ids=[str(getattr(doc, "doc_id", ""))
                                                      for doc in authoritative_docs],
                     score_threshold_arg=None if score_threshold is None else _round_score(score_threshold),
                     latency_ms=_round_ms(rerank_latency)),
            )

            # rerank 阶段展示候选池内的全部候选（按本模式的实际决策顺序）
            final_ids = {str(getattr(d, "doc_id", "")) for d, _ in final_pairs}
            stage_order = stage_pairs + [(doc, score) for doc, score in scored_pairs
                                         if str(getattr(doc, "doc_id", "")) not in final_ids
                                         and str(getattr(doc, "doc_id", "")) not in
                                         {str(getattr(d, "doc_id", "")) for d, _ in stage_pairs}]
            rerank_results = self._pairs_to_results(stage_order)
            final_source = "rerank"

        # ---- 组装 stages（固定顺序：optimize_prompt, dense, bm25, rrf, rerank） ----
        stage_map: Dict[str, dict] = {
            "optimize_prompt": self._make_stage(
                "optimize_prompt",
                opt_latency,
                [],
                extra=dict(optimized),
            )
        }
        if use_dense:
            stage_map["dense"] = self._make_stage(
                "dense", dense_latency, self._make_results(dense_ids, dense_scores, doc_map),
                extra=dense_extra,
            )
        if use_bm25:
            stage_map["bm25"] = self._make_stage(
                "bm25", bm25_latency, self._make_results(bm25_ids, bm25_scores, doc_map),
                extra=bm25_extra,
            )
        if do_rrf:
            stage_map["rrf"] = self._make_stage(
                "rrf", rrf_latency, self._make_results(rrf_ids, rrf_scores, doc_map),
                extra=rrf_extra,
            )
        if do_rerank:
            stage_map["rerank"] = self._make_stage("rerank", rerank_latency, rerank_results,
                                                   extra=rerank_extra)
        if hyde_ids:
            stage_map["hyde"] = self._make_stage(
                "hyde", hyde_latency, self._make_results(hyde_ids, hyde_scores, doc_map)
            )

        stages = [stage_map[name] for name in PIPELINE_STAGE_ORDER if name in stage_map]

        # ---- final ----
        if do_rerank:
            final_results = self._pairs_to_results(final_pairs)
        else:
            final_results = [dict(item) for item in stage_map[final_source]["results"][:final_top_k]]
            for pos, item in enumerate(final_results):
                item["rank"] = pos + 1

        final = {
            "source": final_source,
            "doc_ids": [item["doc_id"] for item in final_results],
            "count": len(final_results),
            "results": final_results,
        }

        _add_trace(
            trace,
            final_source,
            "最终检索结果",
            {
                "source": final_source,
                "final_count": len(final_results),
                "doc_ids": final["doc_ids"],
                "enabled_pipeline": [stage["name"] for stage in stages],
            },
        )

        return {
            "stages": stages,
            "final": final,
            "logs": trace.get_all_trace() if trace is not None else [],
            "optimized": dict(optimized),
            "enabled_pipeline": [stage["name"] for stage in stages],
        }

    def retrieve_documents_with_scores(self, query: str,
                                       raw_top_k: int = RC.DEFAULT_RAW_TOP_K,
                                       final_top_k: int = RC.DEFAULT_FINAL_TOP_K,
                                       **kwargs) -> Tuple[list, Dict[str, float]]:
        """生产检索入口（带分数）：返回 ``(Document 列表, {doc_id: cross-encoder 分})``。

        分数与 ``run()`` 的 ``final.results[*].score`` 完全同源，供 Evaluator 做证据分级。
        注意：blend 模式下 final 的**排序**由融合分决定，``score`` 仍是 cross-encoder 概率，
        因此调用方应取 ``max(scores.values())`` 而不是「第一条的分数」。
        """
        result = self.run(query, raw_top_k=raw_top_k, final_top_k=final_top_k, **kwargs)
        final = result.get("final") or {}
        doc_ids = [str(i) for i in (final.get("doc_ids") or [])]
        score_map: Dict[str, float] = {}
        for item in final.get("results") or []:
            doc_id = str(item.get("doc_id", ""))
            if doc_id:
                score_map[doc_id] = _round_score(item.get("score", 0.0))
        if not doc_ids:
            return [], {}
        doc_map, missing = self._load_documents(doc_ids)
        if missing:
            _add_trace(
                kwargs.get("trace"),
                "retrieve_documents",
                "候选 doc_id 未解析为 Document，已跳过",
                {"missing_ids": missing},
            )
        docs = [doc_map[key] for key in doc_ids if key in doc_map]
        return docs, {str(getattr(doc, "doc_id", "")): score_map.get(str(getattr(doc, "doc_id", "")), 0.0)
                      for doc in docs}

    def retrieve_documents(self, query: str, raw_top_k: int = RC.DEFAULT_RAW_TOP_K,
                           final_top_k: int = RC.DEFAULT_FINAL_TOP_K, **kwargs) -> list:
        """生产检索入口：与 ``run()`` 完全同路径，额外把最终 doc_ids 装配成 Document 列表。

        RAG_agent / 引导链路需要 ``doc.problem / solution / content / emotion`` 等对象属性，
        而 ``run()`` 按调试契约返回纯 JSON（doc_view dict）。本方法复用 run() 内部同一套
        ``_load_documents`` 装载逻辑，保证「调试台看到的排名」与「线上 Document 顺序」恒等。
        """
        docs, _ = self.retrieve_documents_with_scores(query, raw_top_k, final_top_k, **kwargs)
        return docs


def run_pipeline(query: str, **kwargs) -> dict:
    """便捷入口：内部用 ``get_retrieval_components()`` 组装单例组件后执行 ``run()``。

    未显式传 ``trace`` 时自动挂一个独立 ``TraceTracker``，便于脚本直接拿到 ``logs``；
    显式传 ``trace=None`` 时按 ``run()`` 契约返回 ``logs=[]``。
    """
    if "trace" not in kwargs:
        kwargs["trace"] = TraceTracker(False)
    components = get_retrieval_components()
    pipeline = RetrievalPipeline(**components)
    return pipeline.run(query, **kwargs)
