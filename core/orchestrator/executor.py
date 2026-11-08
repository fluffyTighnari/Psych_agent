# -*- coding: utf-8 -*-
"""Executor：顺序执行 Plan 步骤，把步骤结果收敛为结构化返回。

阶段 3-C：
- run_guided       -> guided_plan（引导问答链，编排层 plans/）
- ensure_session   -> 新会话生成 session_id + 检索相似记忆（仅新会话）
- run_agent        -> 调路由 AgentExecutor（依赖注入，避免与 agent.py 循环 import）
- persist_history  -> 确认是心理咨询回复后写 full_chat_history
- direct 步骤链异常 / Budget 超限 -> fallback.run_direct_fallback 保底

阶段 4 起 flexible 步骤将在此开局部 ReAct 循环，Evaluator 评估结果并触发 CRAG 补救。
"""
from langchain_core.messages import HumanMessage, AIMessage

from core.helper.trace_tracker import GLOBAL_TRACKER
from core.meta_db.context_meta import SESSION_STATE
from core.orchestrator.budget import Budget
from core.orchestrator.evaluator import (
    parse_tool_result, evaluate_step, strip_sentinels, FAILURE, EVIDENCE_GAP,
)
from core.orchestrator.fallback import run_direct_fallback
from core.orchestrator.plan import (
    Plan,
    ACT_GUIDED, ACT_ENSURE_SESSION, ACT_RUN_AGENT, ACT_PERSIST_HISTORY,
)
from core.orchestrator.plans.guided_plan import guided_reasoning
from core.tools import search_related_memories, generate_session_id


def _ensure_session(state, problem: str) -> None:
    """新心理咨询会话：生成 session_id + 检索相似记忆（旧行为，仅新会话触发）。"""
    if state.session_id:
        return
    state.session_id = generate_session_id()
    GLOBAL_TRACKER.clear_trace()
    mems = search_related_memories(problem)
    state.similar_memories = mems
    state.referenced_doc_ids.clear()
    GLOBAL_TRACKER.add_trace(
        stage="session_init",
        label="新会话已生成并检索相似记忆",
        content={"session_id": state.session_id,
                 "memory_count": len(mems),
                 "memory_ids": [m.id for m in mems]},
    )


def _build_lc_history(state):
    """full_chat_history -> LangChain 消息列表（仅心理咨询对话）。"""
    lc_history = []
    for msg in state.full_chat_history:
        if msg["role"] == "user":
            lc_history.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            lc_history.append(AIMessage(content=msg["content"]))
    return lc_history


def _run_agent(agent_executor, problem: str, situation: str, lc_history) -> str:
    """调路由 AgentExecutor，返回原始字符串输出。"""
    # 每轮（一次 invoke）开始前重置检索预算 + 证据状态（代码层硬限制，防跨轮泄漏）
    SESSION_STATE.reset_turn_runtime()
    routing_input = problem + ("\n【具体情境】\n" + situation if situation else "")
    invoke_kwargs = {"input": routing_input, "chat_history": lc_history}
    res = agent_executor.invoke(invoke_kwargs)
    return res["output"]


def _persist_history(state, problem: str, raw_output: str) -> None:
    """确认是心理咨询回复后，把本轮 user/assistant 写入会话历史。"""
    if "【心理咨询回复】" not in raw_output:
        return
    state.full_chat_history.append({"role": "user", "content": problem})
    # 落库前剥离哨兵：完整历史会回灌给前端渲染，不能带【心理咨询回复】这类协议标记
    state.full_chat_history.append({
        "role": "assistant",
        "content": strip_sentinels(raw_output),
        "speaker": "advisor",
    })
    state.last_consult_query = problem
    state.save_state()
    GLOBAL_TRACKER.add_trace(
        stage="session_save",
        label="心理咨询回复完成，会话状态已保存",
        content={"dialogue_turns": len(state.full_chat_history),
                 "referenced_docs": len(state.referenced_doc_ids),
                 "similar_memories": len(state.similar_memories),
                 "session_id": state.session_id},
    )


def execute(plan: Plan, *, state, problem: str, situation: str,
            agent_executor, budget: Budget = None) -> dict:
    """按计划执行，返回与旧 agent_service_entry 完全一致的 dict 结构。"""
    budget = budget or Budget()
    actions = plan.actions()

    # 引导线路：单步直接走 guided_plan（其内部已有 LLM 失败友好兜底）
    if ACT_GUIDED in actions:
        budget.record_step()
        result = guided_reasoning(problem, situation=situation)
        return {
            "intent_type": "guided_reason",
            "reply": result["reply"],
            "ended": result.get("ended", False),
        }

    # 直接线路：构建 LangChain 对话历史
    lc_history = _build_lc_history(state)
    raw_output = ""

    try:
        for step in plan.steps:
            budget.record_step()
            if step.action == ACT_ENSURE_SESSION:
                _ensure_session(state, problem)
            elif step.action == ACT_RUN_AGENT:
                budget.record_llm_call()
                raw_output = _run_agent(agent_executor, problem, situation, lc_history)
                # Evaluator 步骤评估：failure（原有兜底）/ evidence_gap（阶段 4-C）
                step_status = evaluate_step(raw_output, SESSION_STATE.last_evidence)
                if step_status == FAILURE:
                    GLOBAL_TRACKER.add_trace(
                        stage="evaluate",
                        label="步骤结果评估为失败（走原有兜底，不补救）",
                        content={"action": step.action, "raw": raw_output[:120]},
                        is_error=True,
                    )
                elif step_status == EVIDENCE_GAP:
                    # 补救已在 retrieve_knowledge_tool 内执行过一轮（含分解/扩名额）；
                    # 这里读到仍 gap，说明「补了也不足」——清零预算，硬性关闭后续检索，
                    # 保证不会出现 gap→再检索→gap 的循环，回复转为纯理解回应。
                    SESSION_STATE.retrieve_budget_left = 0
                    GLOBAL_TRACKER.add_trace(
                        stage="evaluate",
                        label="检索证据不足（已补救一次，转纯理解回应）",
                        content={
                            "action": step.action,
                            "reason": SESSION_STATE.last_evidence.get("reason"),
                            "top_score": SESSION_STATE.last_evidence.get("top_score"),
                            "remediation_action": SESSION_STATE.last_evidence.get("remediation_action"),
                        },
                    )
            elif step.action == ACT_PERSIST_HISTORY:
                _persist_history(state, problem, raw_output)
    except Exception as exc:
        # 会话初始化/记忆检索/Budget 等失败 → 保底直接路由，不把 500 抛给用户
        return run_direct_fallback(
            problem=problem, situation=situation, lc_history=lc_history,
            agent_executor=agent_executor, error=exc,
        )

    # Evaluator：结构化解析（替代旧哨兵 if/elif 链）
    parsed = parse_tool_result(raw_output)
    return {
        "intent_type": parsed.tool_name,
        "reply": parsed.reply,
        "raw_tool_output": parsed.raw_output,
    }
