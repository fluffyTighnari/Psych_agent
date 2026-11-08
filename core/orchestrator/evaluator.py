# -*- coding: utf-8 -*-
"""Evaluator：把 agent_executor 返回的字符串解析为结构化 ToolResult，
并评估步骤状态（success / failure / evidence_gap）。

- parse_tool_result 抽离自原 agent.py 末尾的 if/elif 哨兵链（7 个前缀 + other）；
- evaluate_status 识别空输出与显式失败哨兵（如【会话总结失败】）；
- evaluate_evidence（阶段 4-C）评估**检索证据**是否充分，返回 ok / evidence_gap；
- evaluate_step 把「回复状态」与「证据状态」合并为步骤级状态，供 Executor 分支。

evidence_gap 的语义边界：它表示「检索到了东西，但不足以支撑基于知识的回答」，
不是「回复失败」。心理场景里知识库是可选参照，所以 evidence_gap 不阻断回复，
只用于触发一次有界补救（扩召回 / 分解重检），补救后仍不足则转纯理解回应。
"""
from typing import Iterable, Optional
from core.helper import retrieval_config as RC
from core.orchestrator.plan import ToolResult

# 步骤状态（Executor 分支依据）
SUCCESS = "success"
FAILURE = "failure"
EVIDENCE_GAP = "evidence_gap"

# 证据缺口原因（写 trace / 决定补救动作，不直接展示给用户）
GAP_EMPTY = "empty"                  # 一篇都没检索到 / 文档全部未解析
GAP_WEAK = "weak"                    # 有召回，但最高 cross-encoder 分低于阈值
GAP_NO_PRINCIPLE = "no_principle"    # 方法类提问，但命中证据里 0 条周记（原则/方案）


# 哨兵前缀 -> tool_name（保持与旧行为完全一致的优先级顺序）
_SENTINEL_TABLE = [
    ("【心理咨询回复】", "psychological_consult"),
    ("【引导提问】", "guided_reason"),
    ("【模糊筛选匹配结果】", "meta_filter"),
    ("【精准文本匹配结果】", "precise_text_filter"),
    ("【记忆搜索结果】", "search_memory"),
    ("【精准记忆筛选结果】", "precise_memory_filter"),
    ("【会话总结完成】", "summarize_memory"),
]

# 显式失败哨兵（工具执行失败而非"无结果"）
_FAILURE_SENTINELS = ["【会话总结失败】", "失败】"]


def strip_sentinels(text: str) -> str:
    """剥离全部工具哨兵前缀，返回可展示的纯文本。

    哨兵（如【心理咨询回复】）是工具与编排层之间的协议标记，
    **不应该出现在用户看到的正文里**。落库与返回前端前都要过一遍。
    """
    out = text or ""
    for prefix, _ in _SENTINEL_TABLE:
        if out.startswith(prefix):
            out = out[len(prefix):]
        # 前缀也可能出现在中间（工具文本被拼接时）
        out = out.replace(prefix, "")
    for marker in _FAILURE_SENTINELS:
        if out.startswith(marker):
            out = ""
    return out.lstrip("\n \t")


def parse_tool_result(raw_output: str) -> ToolResult:
    """按旧优先级顺序解析 agent_executor 的字符串输出。"""
    raw_output = raw_output or ""
    for prefix, tool_name in _SENTINEL_TABLE:
        if prefix in raw_output:
            pure = raw_output.split(prefix)[-1]
            # summarize_memory 的 raw 需拼回完整哨兵（旧行为：落库用完整文本）
            if tool_name == "summarize_memory":
                return ToolResult(
                    tool_name=tool_name,
                    reply=pure.strip(),
                    raw_output=prefix + pure,
                )
            return ToolResult(tool_name=tool_name, reply=strip_sentinels(pure), raw_output=raw_output)
    return ToolResult(
        tool_name="other",
        reply=strip_sentinels(raw_output),
        raw_output=raw_output,
    )


def evaluate_status(raw_output: str) -> str:
    """评估单步输出状态："success" / "failure"。

    - 空输出（LLM/工具未产出）→ failure
    - 命中显式失败哨兵 → failure
    - 其余（含"未找到记录"这类正常空结果）→ success
    """
    if not raw_output or not raw_output.strip():
        return FAILURE
    for marker in _FAILURE_SENTINELS:
        if marker in raw_output:
            return FAILURE
    return SUCCESS


def evaluate_evidence(docs: Optional[Iterable], scores: Optional[dict] = None,
                      query: str = "") -> dict:
    """评估检索证据是否充分（CRAG 的「grade」环节），返回结构化判决。

    判定顺序（先硬缺口，再软缺口，最后 ok）：
    1. ``empty``：0 篇文档 —— 检索没有可交给 LLM 的证据；
    2. ``weak``：文档里最高 cross-encoder 分 < ``EVIDENCE_MIN_TOP_SCORE`` —— 明显不相关；
    3. ``no_principle``：提问含方法类关键词，但证据里 0 条周记（原则/方案），
       只剩日记经历 —— 「只有类似经历、没有可操作方法」；
    4. 其余 ``ok``。

    返回::

        {"status": "ok"|"evidence_gap", "reason": ""|"empty"|"weak"|"no_principle",
         "top_score": float|None, "n_principle": int, "n_experience": int,
         "threshold": float}

    说明：``scores`` 是 {doc_id: cross-encoder 概率}；缺省时跳过第 2 条判定（不猜分数）。
    只用 ``max(scores.values())``，因为 blend 模式下 final 的排序由融合分决定，
    第一条文档的 score 未必是最高分。
    """
    doc_list = list(docs or [])
    n_principle = sum(1 for d in doc_list if getattr(d, "doc_type", "") == "weekly")
    n_experience = sum(1 for d in doc_list if getattr(d, "doc_type", "") == "daily")

    top_score: Optional[float] = None
    if scores:
        try:
            values = [float(v) for v in scores.values() if v is not None]
            top_score = round(max(values), 6) if values else None
        except (TypeError, ValueError):
            top_score = None

    base = {
        "top_score": top_score,
        "n_principle": n_principle,
        "n_experience": n_experience,
        "threshold": RC.EVIDENCE_MIN_TOP_SCORE,
    }

    if not doc_list:
        return dict(base, status=EVIDENCE_GAP, reason=GAP_EMPTY)
    if top_score is not None and top_score < RC.EVIDENCE_MIN_TOP_SCORE:
        return dict(base, status=EVIDENCE_GAP, reason=GAP_WEAK)
    if n_principle == 0 and any(hint in (query or "") for hint in RC.EVIDENCE_METHOD_HINTS):
        return dict(base, status=EVIDENCE_GAP, reason=GAP_NO_PRINCIPLE)
    return dict(base, status=SUCCESS, reason="")


def evaluate_step(raw_output: str, evidence: Optional[dict] = None) -> str:
    """步骤级评估：回复失败优先；其次证据缺口；最后 success。

    Executor 用本函数决定分支：
    - ``failure`` → 保持原有错误兜底（fallback / trace）；
    - ``evidence_gap`` → 补救已在检索工具内做过一轮，这里只记录并**关闭后续检索**
      （把预算清零），保证不会出现「gap → 再检索 → gap」的循环。
    """
    status = evaluate_status(raw_output)
    if status == FAILURE:
        return FAILURE
    if evidence and evidence.get("status") == EVIDENCE_GAP:
        return EVIDENCE_GAP
    return SUCCESS

