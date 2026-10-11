"""可配置检索调试流水线（契约：docs/retrieval_debug_contract.md §1 / §2）。

对外提供：
- ``get_retrieval_components()`` 进程级单例 + ``threading.Lock`` 懒加载，首次调用才装载本地模型
  （embedding / reranker），import 期不加载任何模型；失败时向上抛异常，由 API 层兜底。
- ``RetrievalPipeline.run()`` 按勾选组合 dense / bm25 / rrf / rerank 执行检索，返回纯 JSON 可
  序列化的 ``{"stages", "final", "logs", ...}``。
- ``run_pipeline()`` 模块级便捷函数，内部用 ``get_retrieval_components()`` 组装。

实现说明 / 取舍：

1. **复用生产算法**（``core/helper/retriever.py``，未修改）：dense 检索文本 =
   ``optimized["search_query"] + query``；BM25 token = ``list(jieba.cut(query)) + match_topics +
   keywords``；RRF ``1 / (pos + k)``（pos 从 0 开始，与生产一致）；rerank 调用
   ``reranker.rerank_documents(query, docs, final_top_k, score_threshold)``。
2. **dense 分数 = Chroma 的 L2 距离**（越小越相似），故 dense 阶段 score 比其他阶段小；
   顺序即 Chroma 返回顺序（已按距离升序），rank 从 1 开始。
3. **BM25 分数**：只读调用 ``bm25.bm25.get_scores(tokens)`` 取原始 BM25 分数（不修改
   ``core/helper/BM25.py``），按分数降序、过滤 0 分、取 top ``raw_top_k``，与 ``BM25TagIndexer
   .search()`` 语义一致；若索引对象不可用/无 ``get_scores``（异常回退路径），则退回
   ``bm25.search(tokens, raw_top_k)``，此时 score 字段放「排名倒数」``1 / rank`` 作为占位分数。
4. **rerank 真实分数**：``rerank_documents`` 只返回 Document 不返回分数，因此额外用
   ``pipeline.reranker.model.predict(pairs)`` 复算一遍，pairs 构造规则与 reranker 内部
   ``build_input_text`` 完全一致（summary + weekly 的 problem/solution 或 daily 的 content[:800]），
   按同一阈值（score_threshold 为 None 时用 ``reranker.score_threshold``，默认 0.08）过滤、
   同序排序。最终结果与 ``rerank_documents`` 的返回对齐（不一致时以显式阈值下的自身计算为准，
   并写入一条日志）。
5. **结果里的 ``doc``**：填充契约 §2.4 的 DOC_VIEW 形状 dict（JSON 安全，``json.dumps`` 不会报错；
   ``api/retrieval_debug.py`` 的 ``doc_to_view`` 对 dict 同样幂等可用）。取不到时填 ``None``。
6. **阶段语义**（契约 §2.3）：rrf / rerank 需要候选来源，若 dense 与 bm25 都未勾选（只勾 rrf 或
   只勾 rerank），默认启用双路召回；dense 与 bm25 同时启用时（即使没勾 rrf）也必须融合，并出现
   rrf 阶段。全不勾 / 空 query → ``ValueError("至少选择一种检索方式")``。
7. **Document 加载兜底**：主路径严格用 ``knowledge_loader.load_knowledge(ids)``；但本仓库
   ``config/id_map.json`` 存的是其他机器（Windows）的绝对路径，当前 macOS 检出下该方法会静默返回
   空列表（生产 ``Retriever.retrieve`` 也受此影响）。为保证调试视图可用，若某 id 未解析出
   Document，则回退到契约 §1 列出的 ``KNOWLEDGE_CACHE``（同一批 JSON、同一 doc_id 索引）补齐，
   两者都取不到才计入 missing 并写日志。已向 Lead 报备。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import jieba

from config.path_config import BM25_PATH, COLLECTION_NAME, VECTOR_DB_DIR
from core.helper.trace_tracker import TraceTracker

# 阶段 → 中文标签（契约 §2.2 / 前端展示）
PIPELINE_STAGE_LABELS: Dict[str, str] = {
    "optimize_prompt": "Query 优化",
    "dense": "向量召回(Dense)",
    "bm25": "BM25 关键词召回",
    "rrf": "RRF 融合",
    "rerank": "Cross-Encoder 重排",
}

# 阶段固定顺序（契约 §2.2）
PIPELINE_STAGE_ORDER: Tuple[str, ...] = (
    "optimize_prompt",
    "dense",
    "bm25",
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
    bm25 = BM25TagIndexer(
        documents=[],
        bm25_path=BM25_PATH,
        topic_weight=3,
        keyword_weight=1,
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

    def _optimize_query(self, query: str, trace: Optional[TraceTracker]) -> Tuple[dict, float]:
        """阶段 1：Query 优化（任一阶段启用即执行），返回 (info, latency_ms)。"""
        started = time.perf_counter()
        raw = self.prompt_optimizer.optimize_prompt(query)
        latency_ms = (time.perf_counter() - started) * 1000.0

        data = dict(raw) if isinstance(raw, dict) else {}
        info = {
            "search_query": _as_str(data.get("search_query") or query),
            "match_topics": _as_str_list(data.get("match_topics")),
            "keywords": _as_str_list(data.get("keywords")),
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
                "latency_ms": _round_ms(latency_ms),
            },
        )
        return info, latency_ms

    def _run_dense(self, search_text: str, raw_top_k: int) -> Tuple[List[str], List[float], float]:
        """dense 召回：编码 ``search_query + query`` → Chroma 查询，score 为 L2 距离（越小越好）。"""
        started = time.perf_counter()
        embedding = self.embedding_model.encode(search_text)
        result = self.vector_db.query(embedding, raw_top_k)

        ids = list((result.get("ids") or [[]])[0] or [])
        distances = list((result.get("distances") or [[]])[0] or [])
        scores = [_round_score(d) for d in distances[: len(ids)]]
        if len(scores) < len(ids):
            # 理论上不会发生；兜底避免 rank 与 score 长度错位
            scores.extend([0.0] * (len(ids) - len(scores)))
        latency_ms = (time.perf_counter() - started) * 1000.0
        return [str(i) for i in ids], scores, latency_ms

    def _run_bm25(self, query: str, info: dict, raw_top_k: int) -> Tuple[List[str], List[float], float, str]:
        """BM25 召回：token = jieba(query) + match_topics + keywords，返回 (ids, scores, ms, score_mode)。"""
        started = time.perf_counter()
        tokens = list(jieba.cut(query)) + list(info["match_topics"]) + list(info["keywords"])

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
        return ids, scores, latency_ms, score_mode

    def _rrf_fuse(
        self,
        dense_ids: List[str],
        bm25_ids: List[str],
        rrf_k: int,
    ) -> Tuple[List[str], List[float]]:
        """倒数排名融合，与生产 ``Retriever.rrf_fuse`` 完全一致（pos 从 0 开始）。"""
        rank_score: Dict[str, float] = {}
        for pos, doc_id in enumerate(dense_ids):
            rank_score[doc_id] = rank_score.get(doc_id, 0.0) + 1.0 / (pos + rrf_k)
        for pos, doc_id in enumerate(bm25_ids):
            rank_score[doc_id] = rank_score.get(doc_id, 0.0) + 1.0 / (pos + rrf_k)
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
    def _build_rerank_input(doc) -> str:
        """与 reranker.build_input_text 完全一致：summary + weekly(problem/solution) 或 daily(content[:800])。"""
        text_parts = [doc.summary]
        if doc.doc_type == "weekly":
            text_parts.append(doc.problem)
            text_parts.append(doc.solution)
        else:
            text_parts.append(doc.content[:800])
        return "\n".join(text_parts)

    def _cross_encoder_scores(self, query: str, docs: List[Any]) -> List[Tuple[Any, float]]:
        """用 cross-encoder 复算分数（reranker 不返回分数），按分数降序、稳定排序（同分保持输入顺序）。"""
        pairs = [(query, self._build_rerank_input(doc)) for doc in docs]
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
        raw_top_k: int = 6,
        final_top_k: int = 3,
        rrf_k: int = 60,
        score_threshold: Optional[float] = None,
        trace: Optional[TraceTracker] = None,
    ) -> dict:
        """执行可配置检索流水线，返回纯 JSON 可序列化 dict（契约 §2.2）。"""
        raw_query = (query or "").strip()
        if not raw_query or not any((dense, bm25, rrf, rerank)):
            # 契约 §2.3 规则 5：空输入 / 全不勾
            raise ValueError("至少选择一种检索方式")

        raw_top_k = max(1, _as_int(raw_top_k, 6))
        final_top_k = max(1, _as_int(final_top_k, 3))
        rrf_k = max(1, _as_int(rrf_k, 60))

        use_dense = bool(dense)
        use_bm25 = bool(bm25)
        if not use_dense and not use_bm25:
            # 只勾 rrf / 只勾 rerank 时没有显式召回链路，默认双路（契约 §2.3 行 3/4）
            use_dense = True
            use_bm25 = True
        do_rerank = bool(rerank)
        do_rrf = bool(rrf) or (use_dense and use_bm25)

        # ---- 阶段 1：Query 优化 ----
        optimized, opt_latency = self._optimize_query(raw_query, trace)

        # ---- 阶段 2/3：dense 与 bm25（同时启用时并发，stages 顺序固定 dense 在前） ----
        dense_ids: List[str] = []
        dense_scores: List[float] = []
        dense_latency = 0.0
        bm25_ids: List[str] = []
        bm25_scores: List[float] = []
        bm25_latency = 0.0
        bm25_score_mode = "bm25_raw"

        search_text = optimized["search_query"] + raw_query

        if use_dense and use_bm25:
            outcome: Dict[str, Any] = {}
            errors: Dict[str, BaseException] = {}

            def _dense_job():
                try:
                    outcome["dense"] = self._run_dense(search_text, raw_top_k)
                except BaseException as exc:  # noqa: BLE001 - 原样抛回主线程
                    errors["dense"] = exc

            def _bm25_job():
                try:
                    outcome["bm25"] = self._run_bm25(raw_query, optimized, raw_top_k)
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

            dense_ids, dense_scores, dense_latency = outcome["dense"]
            bm25_ids, bm25_scores, bm25_latency, bm25_score_mode = outcome["bm25"]
        elif use_dense:
            dense_ids, dense_scores, dense_latency = self._run_dense(search_text, raw_top_k)
        elif use_bm25:
            bm25_ids, bm25_scores, bm25_latency, bm25_score_mode = self._run_bm25(raw_query, optimized, raw_top_k)

        if use_dense:
            _add_trace(
                trace,
                "dense",
                "稠密向量检索完成",
                {
                    "search_text": search_text[:200],
                    "top_k": raw_top_k,
                    "hit_ids": dense_ids,
                    "distances": dense_scores,
                    "score_metric": "l2_distance",
                    "latency_ms": _round_ms(dense_latency),
                },
            )
        if use_bm25:
            _add_trace(
                trace,
                "bm25",
                "BM25 稀疏检索完成",
                {
                    "query": raw_query[:120],
                    "match_topics": optimized["match_topics"],
                    "keywords": optimized["keywords"],
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
            rrf_ids, rrf_scores = self._rrf_fuse(dense_ids, bm25_ids, rrf_k)
            rrf_latency = (time.perf_counter() - started) * 1000.0
            _add_trace(
                trace,
                "rrf",
                "RRF 融合完成",
                {
                    "rrf_k": rrf_k,
                    "dense_count": len(dense_ids),
                    "bm25_count": len(bm25_ids),
                    "fused_count": len(rrf_ids),
                    "fused_ids": rrf_ids,
                    "top_scores": rrf_scores[:10],
                    "latency_ms": _round_ms(rrf_latency),
                },
            )

        # ---- 加载 Document（供各阶段展示与 rerank 输入） ----
        upstream_ids: List[str] = rrf_ids if do_rrf else (dense_ids if use_dense else bm25_ids)
        all_ids = list(dense_ids) + list(bm25_ids) + list(rrf_ids) + list(upstream_ids)
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
            upstream_docs = [doc_map[key] for key in upstream_ids if key in doc_map]
            started = time.perf_counter()
            # 契约要求：调用 rerank_documents 决定最终排序与过滤
            authoritative_docs = self.reranker.rerank_documents(
                raw_query, upstream_docs, final_top_k, score_threshold
            )
            # rerank_documents 不返回分数，用同一 build_input_text 规则复算真实 cross-encoder 分数
            scored_pairs = self._cross_encoder_scores(raw_query, upstream_docs)
            rerank_latency = (time.perf_counter() - started) * 1000.0

            default_threshold = float(getattr(self.reranker, "score_threshold", 0.08))
            rerank_threshold = default_threshold if score_threshold is None else float(score_threshold)
            filtered_pairs = [(doc, score) for doc, score in scored_pairs if score >= rerank_threshold]

            authoritative_ids = [str(getattr(doc, "doc_id", "")) for doc in authoritative_docs]
            my_top_ids = [str(getattr(doc, "doc_id", "")) for doc, _ in filtered_pairs[:final_top_k]]

            _add_trace(
                trace,
                "rerank",
                "Cross-Encoder 重排完成",
                {
                    "threshold": _round_score(rerank_threshold),
                    "reranker_default_threshold": _round_score(default_threshold),
                    "score_threshold_arg": None if score_threshold is None else _round_score(score_threshold),
                    "input_count": len(upstream_docs),
                    "before_count": len(scored_pairs),
                    "after_count": len(filtered_pairs),
                    "doc_with_score": [
                        {"doc_id": str(getattr(doc, "doc_id", "")), "score": _round_score(score)}
                        for doc, score in scored_pairs
                    ],
                    "authoritative_ids": authoritative_ids,
                    "latency_ms": _round_ms(rerank_latency),
                },
            )

            # rerank 阶段展示全部过阈值候选（不截断）；final 取前 final_top_k
            rerank_results = self._pairs_to_results(filtered_pairs)

            if authoritative_ids == my_top_ids:
                score_lookup = {str(getattr(doc, "doc_id", "")): score for doc, score in scored_pairs}
                final_pairs = [(doc, score_lookup.get(str(getattr(doc, "doc_id", "")), 0.0)) for doc in authoritative_docs]
            else:
                # 仅当显式传入的 score_threshold 与 reranker 自身阈值不同时会走到这里：
                # reranker 内部固定用自身阈值过滤，此时以显式阈值的自身计算为准并记一条日志。
                _add_trace(
                    trace,
                    "rerank",
                    "显式 score_threshold 与 reranker 内部阈值不同，最终结果按显式阈值计算",
                    {
                        "explicit_threshold": _round_score(rerank_threshold),
                        "reranker_default_threshold": _round_score(default_threshold),
                        "authoritative_ids": authoritative_ids,
                        "computed_ids": my_top_ids,
                    },
                )
                final_pairs = filtered_pairs[:final_top_k]
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
                "dense", dense_latency, self._make_results(dense_ids, dense_scores, doc_map)
            )
        if use_bm25:
            stage_map["bm25"] = self._make_stage(
                "bm25", bm25_latency, self._make_results(bm25_ids, bm25_scores, doc_map)
            )
        if do_rrf:
            stage_map["rrf"] = self._make_stage(
                "rrf", rrf_latency, self._make_results(rrf_ids, rrf_scores, doc_map)
            )
        if do_rerank:
            stage_map["rerank"] = self._make_stage("rerank", rerank_latency, rerank_results)

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
