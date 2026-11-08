from typing import Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.agents import create_openai_tools_agent, AgentExecutor

from config.model_config import GLOBAL_MODEL, get_langchain_llm
from config.prompt_config import agent_prompt
from core.meta_db.context_meta import SESSION_STATE
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.orchestrator.planner import classify_and_plan
from core.orchestrator.executor import execute as execute_plan
from core.tools import (
    meta_filter_tool,
    precise_text_filter_tool,
    psychological_consult_tool,
    retrieve_knowledge_tool,
    summarize_memory_tool,
    search_memory_tool,
    precise_memory_filter_tool,
)
# 全局唯一会话实例，定义在 context_meta.py 中，agent 与 tools 共用
# 编排逻辑（Planner/Executor/Evaluator/Budget）已迁入 core/orchestrator/，
# 本文件只负责：构造路由 Agent、会话模式锁定、异常兜底。

# ===================== 路由Prompt =====================
router_system_prompt = agent_prompt

router_prompt = ChatPromptTemplate.from_messages([
    ("system", router_system_prompt),
    ("placeholder", "{chat_history}"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}")
])

# ===================== LLM & Agent 初始化 =====================

tool_list = [
    meta_filter_tool,
    precise_text_filter_tool,
    retrieve_knowledge_tool,
    psychological_consult_tool,
    summarize_memory_tool,
    search_memory_tool,
    precise_memory_filter_tool,
]
router_llm = get_langchain_llm(GLOBAL_MODEL.chat)
agent = create_openai_tools_agent(router_llm, tool_list, router_prompt)
agent_executor = AgentExecutor(agent=agent, tools=tool_list, verbose=True)


def reset_llm_cache():
    """模型配置更新后由 AppContext.rebuild() 委托调用：重建路由 LLM / Agent。

    意图分类小模型已收编进 AppContext.classify_llm()，由 rebuild() 统一失效，
    不再在此维护全局单例。
    """
    global router_llm, agent, agent_executor
    router_llm = get_langchain_llm(GLOBAL_MODEL.chat)
    agent = create_openai_tools_agent(router_llm, tool_list, router_prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tool_list, verbose=True)


# ===================== 对外统一入口 =====================

def agent_service_entry(user_input: str, situation: str = None, role: str = "advisor", mode: str = None, attachments: list = None) -> Dict[str, Any]:
    """
    对外API统一入口（并发安全包装）：
    - 持有 SESSION_STATE 可重入锁，避免并发请求互相覆盖会话状态；
    - 全程异常兜底：任何 LLM/检索异常转为结构化返回，不再向上抛 500 裸异常。
    """
    with SESSION_STATE.lock:
        try:
            return _agent_service_entry_impl(user_input, situation=situation, role=role, mode=mode, attachments=attachments)
        except Exception as e:
            GLOBAL_TRACKER.add_trace(
                stage="chat",
                label="对话处理失败（已兜底）",
                content={"error": str(e), "input": (user_input or "")[:80]},
                is_error=True,
                error_msg=str(e)
            )
            return {
                "intent_type": "error",
                "reply": f"服务暂时不可用：{e}",
                "error": str(e),
            }


def _agent_service_entry_impl(user_input: str, situation: str = None, role: str = "advisor", mode: str = None, attachments: list = None) -> Dict[str, Any]:
    """
    对外API统一入口：
    - mode='guided' → 引导咨询：引导问答循环，【结束】后自动生成建议报告
    - mode='direct' → 直接咨询：建议者/总结者流程（工具路由）
    mode 为会话级模式，首条消息锁定，之后忽略传入值。
    situation：direct 每轮可选；guided 仅锚定首条时采用。
    """
    state = SESSION_STATE
    problem = (user_input or "").strip()
    situation = (situation or "").strip()
    # 本轮用户主动引用的资料：存入会话状态，供 tool 层注入 prompt
    state.attachments = list(attachments or [])

    # ===================== 会话模式：首条锁定 =====================
    if not state.mode:
        if mode in ("direct", "guided"):
            state.mode = mode
        else:
            state.mode = "guided" if role == "guide" else "direct"
        state.save_state()

    if state.mode != "guided":
        state.last_role = "advisor"

    # ===================== Planner -> Executor =====================
    plan = classify_and_plan(problem, state.mode)
    return execute_plan(
        plan,
        state=state,
        problem=problem,
        situation=situation,
        agent_executor=agent_executor,
    )
