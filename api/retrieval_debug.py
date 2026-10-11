"""检索优化调试接口

对外暴露 4 个只读/调试接口（契约 docs/retrieval_debug_contract.md §3）：
- POST /retrieval/debug            勾选 dense/bm25/rrf/rerank 任意组合，返回逐阶段结果与日志
- GET  /retrieval/documents        知识库全量文档视图（keyword / doc_type / 分页）
- GET  /retrieval/documents/{id}   单篇文档视图
- GET  /retrieval/meta             调试面板元信息（主题/计数/模型/默认参数/阶段开关说明）

设计约定：
- 所有响应统一走 api.common.resp()，异常统一由 @catch_exception 兜底（500 + error_detail）。
- 本地模型（embedding/reranker）由 core.helper.retrieval_pipeline 懒加载复用，本模块不在 import 期加载。
- retrieval_pipeline 采用函数内 import，避免其尚未落地时拖垮服务启动。
"""

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.common import CODE_OK, CODE_PARAM_ERR, catch_exception, resp
from config.model_config import EMBEDDING_MODEL, RERANKING_MODEL
from config.path_config import BM25_PATH
from config.topic_config import VALID_TOPICS
from core.helper.knowledge_cache import KNOWLEDGE_CACHE
from core.helper.trace_tracker import TraceTracker, use_tracker, use_tracker_reset

router = APIRouter(prefix="/retrieval", tags=["检索优化调试"])

# ===================== 默认值与合法区间（与契约 §3 一致） =====================
DEFAULT_RAW_TOP_K = 6
DEFAULT_FINAL_TOP_K = 3
DEFAULT_RRF_K = 60
DEFAULT_SCORE_THRESHOLD = 0.08

RAW_TOP_K_RANGE = (1, 50)
FINAL_TOP_K_RANGE = (1, 50)
RRF_K_RANGE = (1, 1000)
SCORE_THRESHOLD_RANGE = (0.0, 1.0)

DOC_LIMIT_DEFAULT = 200
DOC_LIMIT_RANGE = (1, 500)
DOC_TYPES = ("daily", "weekly")

# 调试面板的阶段说明（顺序即执行顺序，供前端渲染开关/说明卡片）
STAGE_DEFS = [
    {
        "name": "optimize_prompt",
        "label": "Query 优化",
        "desc": "调用本地 LLM 将原始提问改写为检索用 search_query，并抽取 match_topics 与 keywords，供后续两条召回链路复用。",
    },
    {
        "name": "dense",
        "label": "Dense 向量召回",
        "desc": "把 search_query 与原始提问编码为向量，在 ChromaDB 中按相似度召回 raw_top_k 篇候选，擅长语义相近的表达。",
    },
    {
        "name": "bm25",
        "label": "BM25 稀疏召回",
        "desc": "对原始提问分词并叠加 match_topics/keywords 构造词项，在 BM25 标签索引中召回 raw_top_k 篇候选，擅长关键词精确命中。",
    },
    {
        "name": "rrf",
        "label": "RRF 融合",
        "desc": "用倒数排名融合（k=rrf_k）合并 dense 与 BM25 候选；只要两条召回链路同时启用即自动执行，无需单独依赖。",
    },
    {
        "name": "rerank",
        "label": "Rerank 重排",
        "desc": "用 bge-reranker 交叉编码器对上游候选逐条打分，过滤低于 score_threshold 的结果并截断到 final_top_k。",
    },
]


# ===================== 序列化工具 =====================
def _get(src: Any, name: str, default: Any = None) -> Any:
    """兼容 Document 对象与 dict 两种形态的字段读取。"""
    if isinstance(src, dict):
        return src.get(name, default)
    return getattr(src, name, default)


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


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def doc_to_view(doc: Any) -> Optional[Dict[str, Any]]:
    """把 Document（或同形 dict）转成前端统一使用的 DOC_VIEW；None 原样返回 None。"""
    if doc is None:
        return None
    if not isinstance(doc, dict) and not hasattr(doc, "doc_id"):
        return None
    return {
        "doc_id": _as_str(_get(doc, "doc_id")),
        "title": _as_str(_get(doc, "title")),
        "doc_type": _as_str(_get(doc, "doc_type")),
        "date": _as_str(_get(doc, "date")),
        "source": _as_str(_get(doc, "source")),
        "relative_path": _as_str(_get(doc, "relative_path")),
        "knowledge_path": _as_str(_get(doc, "knowledge_path")),
        "summary": _as_str(_get(doc, "summary")),
        "topic": _as_str_list(_get(doc, "topic")),
        "keywords": _as_str_list(_get(doc, "keywords")),
        "emotion": _as_dict(_get(doc, "emotion")),
        "problem": _as_opt_str(_get(doc, "problem")),
        "analysis": _as_opt_str(_get(doc, "analysis")),
        "solution": _as_opt_str(_get(doc, "solution")),
        "word_count": _as_int(_get(doc, "word_count"), 0),
        "content": _as_str(_get(doc, "content")),
    }


def _convert_results(results: Any) -> List[Dict[str, Any]]:
    """把阶段/final 的 results 列表中的 doc 统一替换成 DOC_VIEW。"""
    converted: List[Dict[str, Any]] = []
    for item in results or []:
        if not isinstance(item, dict):
            converted.append({"doc": doc_to_view(item)})
            continue
        row = dict(item)
        row["doc"] = doc_to_view(item.get("doc"))
        converted.append(row)
    return converted


def _convert_stages(stages: Any) -> List[Dict[str, Any]]:
    converted: List[Dict[str, Any]] = []
    for stage in stages or []:
        if not isinstance(stage, dict):
            continue
        item = dict(stage)
        item["results"] = _convert_results(stage.get("results"))
        converted.append(item)
    return converted


def _convert_final(final: Any) -> Dict[str, Any]:
    if not isinstance(final, dict):
        return {"source": "", "doc_ids": [], "count": 0, "results": []}
    converted = _convert_results(final.get("results"))
    count = _as_int(final.get("count"), len(converted))
    return {
        "source": _as_str(final.get("source")),
        "doc_ids": _as_str_list(final.get("doc_ids")),
        "count": count,
        "results": converted,
    }


def _extract_optimized(stages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从 optimize_prompt 阶段的 extra 字段取 Query 优化结果；缺失/异常时给空结构兜底。"""
    empty = {"search_query": "", "match_topics": [], "keywords": []}
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("name") != "optimize_prompt":
            continue
        extra = stage.get("extra")
        if not isinstance(extra, dict):
            return empty
        return {
            "search_query": _as_str(extra.get("search_query")),
            "match_topics": _as_str_list(extra.get("match_topics")),
            "keywords": _as_str_list(extra.get("keywords")),
        }
    return empty


# ===================== 入参模型 =====================
class RetrievalDebugReq(BaseModel):
    """检索调试请求体；query 必填非空，其余均可选（契约 §3.1）。

    这里刻意不加 Field 的区间约束：FastAPI 的校验失败会直接返回 422，
    而契约要求参数不合法时仍返回 resp(CODE_PARAM_ERR, "参数不合法: ...")，
    因此统一在接口内部手动校验。
    """

    query: str = Field("", description="用户原始提问，必填非空")
    dense: bool = Field(True, description="是否启用 Dense 向量召回")
    bm25: bool = Field(True, description="是否启用 BM25 稀疏召回")
    rrf: bool = Field(True, description="是否启用 RRF 融合")
    rerank: bool = Field(True, description="是否启用 Rerank 重排")
    raw_top_k: int = Field(DEFAULT_RAW_TOP_K, description="召回阶段候选数")
    final_top_k: int = Field(DEFAULT_FINAL_TOP_K, description="最终返回候选数")
    rrf_k: int = Field(DEFAULT_RRF_K, description="RRF 融合常数 k")
    score_threshold: Optional[float] = Field(None, description="重排分数阈值，null 表示用默认值")


def _validate_debug_req(req: RetrievalDebugReq) -> Optional[str]:
    """返回首个校验错误信息；全部合法返回 None。"""
    if not (req.query or "").strip():
        return "query 不能为空"
    if not (RAW_TOP_K_RANGE[0] <= req.raw_top_k <= RAW_TOP_K_RANGE[1]):
        return f"raw_top_k 需在 [{RAW_TOP_K_RANGE[0]},{RAW_TOP_K_RANGE[1]}] 区间"
    if not (FINAL_TOP_K_RANGE[0] <= req.final_top_k <= FINAL_TOP_K_RANGE[1]):
        return f"final_top_k 需在 [{FINAL_TOP_K_RANGE[0]},{FINAL_TOP_K_RANGE[1]}] 区间"
    if not (RRF_K_RANGE[0] <= req.rrf_k <= RRF_K_RANGE[1]):
        return f"rrf_k 需在 [{RRF_K_RANGE[0]},{RRF_K_RANGE[1]}] 区间"
    if req.score_threshold is not None and not (
        SCORE_THRESHOLD_RANGE[0] <= req.score_threshold <= SCORE_THRESHOLD_RANGE[1]
    ):
        return f"score_threshold 需在 [{SCORE_THRESHOLD_RANGE[0]},{SCORE_THRESHOLD_RANGE[1]}] 区间或为 null"
    if not any((req.dense, req.bm25, req.rrf, req.rerank)):
        return "至少选择一种检索方式"
    return None


# ===================== 接口 1：POST /retrieval/debug =====================
@router.post("/debug")
@catch_exception
def run_retrieval_debug(req: RetrievalDebugReq):
    """按勾选组合执行检索流水线，返回逐阶段结果、最终结果与结构化日志。"""
    err = _validate_debug_req(req)
    if err:
        return resp(CODE_PARAM_ERR, f"参数不合法: {err}")

    # 函数内 import：retrieval_pipeline 由 pipeline-dev 并行交付，未落地时不影响本模块其余接口
    from core.helper.retrieval_pipeline import RetrievalPipeline, get_retrieval_components

    query = req.query.strip()

    # 每次请求独立 trace 实例，并把它设为「本次请求的 trace」：此后本请求内所有写
    # GLOBAL_TRACKER 的既有组件（组件首次懒加载 / reranker / loader / BM25 ...）都会被
    # 自动改写到该实例 → 既拿到完整日志，又完全不污染 /trace/stream 的全局日志流。
    # 注意：use_tracker 必须早于 get_retrieval_components()，否则首次组件装载（BM25 索引加载）
    # 的日志会在重定向生效前写进全局日志。
    trace = TraceTracker(False)
    started = time.perf_counter()
    trace_token = use_tracker(trace)
    try:
        components = get_retrieval_components() or {}
        pipeline = RetrievalPipeline(
            embedding_model=components.get("embedding_model"),
            vector_db=components.get("vector_db"),
            bm25=components.get("bm25"),
            prompt_optimizer=components.get("prompt_optimizer"),
            knowledge_loader=components.get("knowledge_loader"),
            reranker=components.get("reranker"),
        )
        raw = pipeline.run(
            query,
            dense=req.dense,
            bm25=req.bm25,
            rrf=req.rrf,
            rerank=req.rerank,
            raw_top_k=req.raw_top_k,
            final_top_k=req.final_top_k,
            rrf_k=req.rrf_k,
            score_threshold=req.score_threshold,
            trace=trace,
        )
    except ValueError as exc:
        # 契约 §2.3 规则 5：全不勾 / 空输入等参数类错误统一 400
        return resp(CODE_PARAM_ERR, f"参数不合法: {exc}")
    finally:
        use_tracker_reset(trace_token)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    raw = raw if isinstance(raw, dict) else {}
    stages = _convert_stages(raw.get("stages"))
    final = _convert_final(raw.get("final"))
    logs = raw.get("logs")
    if not isinstance(logs, list) or not logs:
        logs = trace.get_all_trace()

    data = {
        "query": query,
        "flags": {
            "dense": bool(req.dense),
            "bm25": bool(req.bm25),
            "rrf": bool(req.rrf),
            "rerank": bool(req.rerank),
        },
        "params": {
            "raw_top_k": req.raw_top_k,
            "final_top_k": req.final_top_k,
            "rrf_k": req.rrf_k,
            "score_threshold": (
                DEFAULT_SCORE_THRESHOLD if req.score_threshold is None else req.score_threshold
            ),
        },
        "enabled_pipeline": [str(s.get("name", "")) for s in stages if isinstance(s, dict)],
        "optimized": _extract_optimized(stages),
        "stages": stages,
        "final": final,
        # 最终结果摘要块（Lead 裁决）：doc_ids 直接复用 final.doc_ids，避免前端二次拼装
        "final_summary": {
            "source": final["source"],
            "label": "最终结果",
            "desc": "按所选链路输出的最终 Top-K",
            "count": final["count"],
            "doc_ids": final["doc_ids"],
        },
        "latency_ms": latency_ms,
        "logs": logs,
    }
    return resp(CODE_OK, "检索调试完成", data=data)


# ===================== 接口 2：GET /retrieval/documents =====================
def _doc_search_text(doc: Any) -> str:
    parts = [
        _as_str(_get(doc, "title")),
        _as_str(_get(doc, "summary")),
        _as_str(_get(doc, "content")),
        " ".join(_as_str_list(_get(doc, "keywords"))),
    ]
    return "\n".join(parts).lower()


def _sorted_documents(docs: List[Any]) -> List[Any]:
    """date 降序（date 为空排最后），同 date 按 title 升序；两次稳定排序实现。"""
    dated = [d for d in docs if _as_str(_get(d, "date")).strip()]
    undated = [d for d in docs if not _as_str(_get(d, "date")).strip()]
    dated.sort(key=lambda d: _as_str(_get(d, "title")))
    dated.sort(key=lambda d: _as_str(_get(d, "date")).strip(), reverse=True)
    undated.sort(key=lambda d: _as_str(_get(d, "title")))
    return dated + undated


@router.get("/documents")
@catch_exception
def list_knowledge_documents(
    keyword: Optional[str] = None,
    doc_type: Optional[str] = None,
    limit: int = DOC_LIMIT_DEFAULT,
    offset: int = 0,
):
    """知识库全量文档视图，支持关键词模糊过滤、类型过滤与分页。"""
    if not (DOC_LIMIT_RANGE[0] <= limit <= DOC_LIMIT_RANGE[1]):
        return resp(CODE_PARAM_ERR, f"参数不合法: limit 需在 [{DOC_LIMIT_RANGE[0]},{DOC_LIMIT_RANGE[1]}] 区间")
    if offset < 0:
        return resp(CODE_PARAM_ERR, "参数不合法: offset 不能为负数")

    normalized_type = (doc_type or "").strip().lower()
    if normalized_type and normalized_type not in DOC_TYPES:
        return resp(CODE_PARAM_ERR, "参数不合法: doc_type 仅支持 daily / weekly")

    kw = (keyword or "").strip().lower()
    docs = list(KNOWLEDGE_CACHE.documents)
    if kw:
        docs = [d for d in docs if kw in _doc_search_text(d)]

    # doc_types 统计基于「关键词过滤后、类型过滤前」的集合，便于前端在按类型筛选时仍看到两类数量
    type_counter: Dict[str, int] = {}
    for d in docs:
        key = _as_str(_get(d, "doc_type")) or "unknown"
        type_counter[key] = type_counter.get(key, 0) + 1
    doc_types = {key: type_counter[key] for key in sorted(type_counter)}

    if normalized_type:
        docs = [d for d in docs if _as_str(_get(d, "doc_type")).lower() == normalized_type]

    ordered = _sorted_documents(docs)
    total = len(ordered)
    page = ordered[offset: offset + limit] if limit > 0 else []

    data = {
        "total": total,
        "count": len(page),
        "offset": offset,
        "limit": limit,
        "doc_types": doc_types,
        "documents": [doc_to_view(d) for d in page],
    }
    return resp(CODE_OK, "加载知识库文档成功", data=data)


# ===================== 接口 3：GET /retrieval/documents/{doc_id} =====================
@router.get("/documents/{doc_id}")
@catch_exception
def get_knowledge_document(doc_id: str):
    """单篇文档视图；未命中返回 CODE_PARAM_ERR + 文档不存在。"""
    target = str(doc_id).strip()
    doc = KNOWLEDGE_CACHE.cache.get(target)
    if doc is None:
        for candidate in KNOWLEDGE_CACHE.documents:
            if _as_str(_get(candidate, "doc_id")) == target:
                doc = candidate
                break
    if doc is None:
        return resp(CODE_PARAM_ERR, "文档不存在")
    return resp(CODE_OK, "加载文档详情成功", data={"document": doc_to_view(doc)})


# ===================== 接口 4：GET /retrieval/meta =====================
def _model_display_name(path: Any) -> str:
    """把模型路径转成展示名：HF 缓存目录 models--BAAI--bge-reranker-base → bge-reranker-base。"""
    name = getattr(path, "name", None) or str(path)
    if name.startswith("models--"):
        parts = [p for p in name.split("--") if p]
        if parts:
            return parts[-1]
    return name


@router.get("/meta")
@catch_exception
def get_retrieval_meta():
    """调试面板元信息：主题集合、文档/向量计数、模型名、默认参数、阶段说明。"""
    # 函数内 import：避免 import 期就创建 ChromaDB 客户端
    from config.path_config import COLLECTION_NAME, VECTOR_DB_DIR
    from core.vector_db.documents_vector_db import VectorDB

    vector_count = None
    try:
        vector_count = int(VectorDB(VECTOR_DB_DIR, COLLECTION_NAME).count())
    except Exception:
        vector_count = None

    data = {
        "topics": sorted(VALID_TOPICS),
        "doc_count": len(KNOWLEDGE_CACHE.documents),
        "vector_count": vector_count,
        "bm25_ready": bool(BM25_PATH.exists()),
        "models": {
            "embedding": _model_display_name(EMBEDDING_MODEL),
            "reranker": _model_display_name(RERANKING_MODEL),
        },
        "defaults": {
            "raw_top_k": DEFAULT_RAW_TOP_K,
            "final_top_k": DEFAULT_FINAL_TOP_K,
            "rrf_k": DEFAULT_RRF_K,
            "score_threshold": DEFAULT_SCORE_THRESHOLD,
        },
        "stages": [dict(stage) for stage in STAGE_DEFS],
    }
    return resp(CODE_OK, "获取检索调试元信息成功", data=data)
