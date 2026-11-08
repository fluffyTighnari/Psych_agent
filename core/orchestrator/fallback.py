# -*- coding: utf-8 -*-
"""Fallback：编排失败时的确定性保底链路。

阶段 3-C：direct 路径的步骤执行若抛异常（记忆检索失败、Budget 超限等），
不再直接 500，而是回退到最简单的确定性动作——直接调一次路由 AgentExecutor，
让用户仍能得到回复；保底链路也失败时才返回结构化 error（由 agent_service_entry
的最外层兜底负责）。guided 路径在 guided_plan 内部已有自己的友好错误兜底。
"""
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.meta_db.context_meta import SESSION_STATE
from core.orchestrator.evaluator import parse_tool_result


def run_direct_fallback(*, problem: str, situation: str, lc_history,
                        agent_executor, error: Exception) -> dict:
    """direct 编排失败 → 跳过会话初始化/记忆检索等步骤，直接路由 Agent。"""
    GLOBAL_TRACKER.add_trace(
        stage="fallback",
        label="编排步骤失败，回退直接路由 Agent",
        content={"error": str(error)[:200], "input": (problem or "")[:80]},
        is_error=True,
        error_msg=str(error),
    )
    routing_input = problem + ("\n【具体情境】\n" + situation if situation else "")
    # 保底链路同样是一次 invoke：重置本轮检索预算与证据状态，避免计数/状态泄漏
    SESSION_STATE.reset_turn_runtime()
    res = agent_executor.invoke({"input": routing_input, "chat_history": lc_history})
    parsed = parse_tool_result(res["output"])
    return {
        "intent_type": parsed.tool_name,
        "reply": parsed.reply,
        "raw_tool_output": parsed.raw_output,
    }
