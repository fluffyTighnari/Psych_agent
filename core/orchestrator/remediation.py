# -*- coding: utf-8 -*-
"""CRAG 式补救：证据不足时执行「恰好一次」的纠正检索（阶段 4-C）。

触发链::

    retrieve_knowledge_tool
      → rag_agent.retrieve_scored()        # 第一次检索（消耗 1 次预算）
      → Evaluator.evaluate_evidence()      # grade：ok / evidence_gap
      → remediate_once()                   # gap 时纠正：分解查询 + 扩召回名额
      → merge_evidence()                   # 首次证据 ∪ 补救证据，取 final_top_k
      → 交 psychological_consult_tool 生成（不再检索）

三条硬约束（本模块是唯一实现点，不要把补救散回工具层）：

1. **只补一次**：``state.remediation_count`` 上限 1，绝不递归、不 while 循环；
2. **预算共用**：补救消耗 ``state.retrieve_budget_left``（与 LLM 工具调用同一个计数器），
   因此「首次 + 补救」正好用满 ``RETRIEVE_BUDGET_PER_TURN = 2``，补救绕不过硬预算；
3. **失败可降级**：分解失败 / 检索异常 → 返回空结果，调用方继续用首次证据回复。
"""
from typing import List, Optional

from core.helper import retrieval_config as RC
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.orchestrator.evaluator import GAP_EMPTY, GAP_NO_PRINCIPLE, GAP_WEAK


def merge_evidence(primary_docs: list, primary_scores: dict,
                   extra_docs: list, extra_scores: dict,
                   final_top_k: int = RC.DEFAULT_FINAL_TOP_K) -> tuple:
    """合并两批证据（首次检索 ∪ 补救检索），按「最高分 + 覆盖次数」排序去重。

    排序键 = ``最高 cross-encoder 分 + 0.05 × (两批都命中的次数-1)``（封顶 1.0）。
    返回 ``(docs, {doc_id: best_score})``，条数不超过 ``final_top_k``。
    """
    merged: dict[str, dict] = {}

    def _absorb(docs, scores):
        for rank, doc in enumerate(docs or []):
            doc_id = str(getattr(doc, "doc_id", ""))
            if not doc_id:
                continue
            score = float((scores or {}).get(doc_id, 0.0))
            item = merged.get(doc_id)
            if item is None:
                merged[doc_id] = {"doc": doc, "best": score, "hits": 1, "first_rank": rank}
            else:
                item["best"] = max(item["best"], score)
                item["hits"] += 1
                item["first_rank"] = min(item["first_rank"], rank)

    _absorb(primary_docs, primary_scores)
    _absorb(extra_docs, extra_scores)

    def sort_key(pair):
        item = pair[1]
        total = min(1.0, item["best"] + 0.05 * (item["hits"] - 1))
        return (total, -item["first_rank"])

    ordered = sorted(merged.items(), key=sort_key, reverse=True)[:max(1, int(final_top_k))]
    docs = [item["doc"] for _, item in ordered]
    scores = {doc_id: round(float(item["best"]), 6) for doc_id, item in ordered}
    return docs, scores


def remediate_once(rag_agent, query: str, gap_reason: str, state) -> dict:
    """执行一次纠正检索；任何前置条件不满足时返回空结果（不抛异常）。

    参数：
    - ``rag_agent``：``PsychRAGAgent``（需提供 ``retrieve_multi``）
    - ``query``：用户本轮的核心检索短语
    - ``gap_reason``：Evaluator 给出的 ``empty / weak / no_principle``
    - ``state``：``SingleSessionState``（读写 retrieve_budget_left / remediation_count）

    返回 ``{"docs","scores","action","queries","reason"}``；``action`` 取值：
    - ``decompose``：分解为多条子查询后重检
    - ``expand``：未拆出子查询，退化为单查询扩大候选池
    - ``budget_exhausted`` / ``limit_reached`` / ``error``：未执行补救（空结果）
    """
    empty = {"docs": [], "scores": {}, "queries": [], "reason": gap_reason}

    if getattr(state, "remediation_count", 0) >= 1:
        return dict(empty, action="limit_reached")
    if getattr(state, "retrieve_budget_left", 0) <= 0:
        return dict(empty, action="budget_exhausted")

    # 延迟 import：避免 core.tools 包初始化与 orchestrator 形成模块级循环
    from core.tools.primitives import decompose_query

    # 拆分只在「复合/模糊」时产生多条；只拆出一条时走扩名额，语义更保守
    queries: List[str] = decompose_query(query)
    action = "decompose" if len(queries) > 1 else "expand"
    if gap_reason == GAP_EMPTY and len(queries) > 1:
        action = "decompose"

    kwargs = {
        "raw_top_k": RC.REMEDIATION_EXPAND_TOP_K,
        "final_top_k": RC.DEFAULT_FINAL_TOP_K,
        "rerank_pool": RC.REMEDIATION_EXPAND_RERANK_POOL,
    }

    # 补救 = 一次检索调用 → 扣 1 次预算（不因子查询条数多扣，避免绕过预算语义）
    state.retrieve_budget_left -= 1
    state.remediation_count += 1

    try:
        result = rag_agent.retrieve_multi(queries, **kwargs) if len(queries) > 1 \
            else rag_agent.retrieve_scored(query, **kwargs)
        docs = result.get("docs") or []
        scores = result.get("scores") or {}
    except Exception as exc:  # noqa: BLE001 - 补救是可选增强，失败就退回首次证据
        GLOBAL_TRACKER.add_trace(
            stage="remediation",
            label="CRAG 补救检索异常（已降级为首次证据）",
            content={"reason": gap_reason, "queries": queries, "error": str(exc)[:160]},
            is_error=True,
            error_msg=str(exc)[:300],
        )
        return dict(empty, action="error", queries=queries)

    GLOBAL_TRACKER.add_trace(
        stage="remediation",
        label="CRAG 补救检索完成",
        content={
            "reason": gap_reason,
            "action": action,
            "queries": queries,
            "raw_top_k": RC.REMEDIATION_EXPAND_TOP_K,
            "rerank_pool": RC.REMEDIATION_EXPAND_RERANK_POOL,
            "doc_ids": [getattr(d, "doc_id", "") for d in docs],
            "budget_left": state.retrieve_budget_left,
        },
    )
    return {"docs": docs, "scores": scores, "action": action,
            "queries": queries, "reason": gap_reason}
