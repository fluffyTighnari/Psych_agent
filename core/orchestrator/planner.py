# -*- coding: utf-8 -*-
"""Planner：把用户请求翻译为执行计划（Plan）。

阶段 3-B：
- 引导会话（state.mode == guided）直接产出 run_guided 单步计划；
- 直接会话由小模型分类（沿用原 _is_counseling 的二分类 prompt，行为等价），
  心理咨询倾诉产出「ensure_session -> run_agent -> persist_history」三步计划，
  工具请求产出「run_agent」单步计划。
分类小模型从 agent.py 模块级单例收编进 AppContext.classify_llm()。

阶段 4 将把二分类升级为「是否需要检索」的结构化决策，并放开复合意图多步。
"""
from core.infra.context import get_app_context
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.orchestrator.plan import (
    Plan, Step,
    ACT_GUIDED, ACT_ENSURE_SESSION, ACT_RUN_AGENT, ACT_PERSIST_HISTORY,
)

_CLASSIFY_PROMPT = """
        你是预分类处理器，严格二分类，仅输出单个大写单词，不能有任何换行、空格、解释、标点。
        可选输出只有两个：COUNSELING / TOOL

        COUNSELING：单纯倾诉心理情绪、人际关系困扰、内心迷茫，无操作指令。
        TOOL：需要执行查询、总结、检索、筛选等操作指令。

        规则：
        1. 只要明确要求总结/查找/检索/筛选/列出具体资料或记录，一律输出TOOL；
        2. 针对自身情绪、关系、行为的求助（如"我该怎么理解""我该怎么练习""我该不该…"），
           即使含有"怎么/如何/练习/方法"等方法词，也一律输出COUNSELING——它是在求助，不是在要求检索；
        3. 仅单纯心理倾诉输出COUNSELING。

        示例：
        "我该怎么练习先接住对方的情绪？" -> COUNSELING
        "帮我找所有关于自我否定的日记" -> TOOL
        用户输入：{user_input}
        仅输出一个单词：
        """

# TOOL 必须对应「明确的操作指令」。小模型（API 模型 temperature=0 仍有 MoE/批处理抖动）
# 偶发把「我该怎么练习…」判成 TOOL，会漏掉 ensure_session / persist_history 两个副作用，
# 导致该轮对话不入历史。这里做确定性兜底：判成 TOOL 但完全没有操作动词 → 纠正为 COUNSELING。
# 只收「明确指向检索/筛选/列举」的动词，避免把「检查我的想法」这类咨询表达误伤。
_TOOL_ACTION_HINTS = (
    "帮我找", "找一下", "查找", "查一下", "检索", "搜索", "筛选", "列出", "列一下",
    "帮我总结", "总结一下", "汇总", "统计", "导出", "打开知识库",
)


def _has_explicit_tool_action(user_input: str) -> bool:
    text = user_input or ""
    return any(hint in text for hint in _TOOL_ACTION_HINTS)


def classify_counseling(user_input: str) -> bool:
    """快速预分类：True=心理咨询倾诉，False=工具请求。分类失败降级为心理咨询。"""
    model = get_app_context().classify_llm()
    try:
        resp = model.chat([{"role": "user", "content": _CLASSIFY_PROMPT.format(user_input=user_input)}])
        result = "COUNSELING" in (resp or "").upper()
        if not result and not _has_explicit_tool_action(user_input):
            # 确定性纠正：TOOL 却没有任何检索/筛选动词 → 按定义只能是 COUNSELING
            GLOBAL_TRACKER.add_trace(
                stage="classify_intent",
                label="分类为 TOOL 但无明确操作指令，按规则纠正为 COUNSELING",
                content={"resp": (resp or "").strip()[:40], "input": user_input[:80]},
            )
            result = True
    except Exception as e:
        # 预分类失败降级：按心理咨询线路处理，不中断用户请求
        GLOBAL_TRACKER.add_trace(
            stage="classify_intent",
            label="意图分类失败，降级为心理咨询线路",
            content={"error": str(e), "input": user_input[:80]},
            is_error=True,
            error_msg=str(e),
        )
        return True
    GLOBAL_TRACKER.add_trace(
        stage="classify_intent",
        label="意图分类完成",
        content={"result": "COUNSELING" if result else "TOOL", "input": user_input[:80]},
    )
    return result


def plan_from_mode(mode: str) -> Plan:
    """会话模式直连：guided 会话直接走引导链，不经过意图判定。"""
    if mode == "guided":
        return Plan(steps=[Step(action=ACT_GUIDED, reason="会话模式=guided")])
    return Plan(steps=[Step(action=ACT_RUN_AGENT, reason="默认直接路由")])


def plan_from_intent(is_counseling: bool) -> Plan:
    """二分类结果 -> 计划。counsel 线路含会话初始化与历史落库两步副作用。"""
    if is_counseling:
        return Plan(steps=[
            Step(action=ACT_ENSURE_SESSION, reason="COUNSELING：新会话初始化+相似记忆检索"),
            Step(action=ACT_RUN_AGENT, reason="COUNSELING：路由 Agent 生成咨询回复",
                 tool_hints=["psychological_consult_tool"]),
            Step(action=ACT_PERSIST_HISTORY, reason="COUNSELING：确认回复后写入会话历史"),
        ])
    return Plan(steps=[Step(action=ACT_RUN_AGENT, reason="TOOL：直接路由 Agent", tool_hints=[])])


def classify_and_plan(user_input: str, mode: str) -> Plan:
    """Planner 主入口：会话模式 + 小模型分类 -> Plan。"""
    if mode == "guided":
        return plan_from_mode(mode)
    return plan_from_intent(classify_counseling(user_input))
