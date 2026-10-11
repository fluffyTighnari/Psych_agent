from typing import Dict, Any

from langchain_core.messages import HumanMessage, AIMessage
from langchain_classic.agents import create_openai_tools_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate

from config.model_config import GLOBAL_MODEL, get_langchain_llm
from config.prompt_config import agent_prompt
from core.llm import LLM
from core.meta_db.context_meta import SESSION_STATE
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.tools import (
    meta_filter_tool,
    precise_text_filter_tool,
    psychological_consult_tool,
    summarize_memory_tool,
    search_memory_tool,
    precise_memory_filter_tool,
    guided_reasoning,
    search_related_memories,
    generate_session_id,
    summarize_memory,
)
# 全局唯一会话实例，定义在 context_meta.py 中，agent 与 tools 共用

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
    psychological_consult_tool,
    summarize_memory_tool,
    search_memory_tool,
    precise_memory_filter_tool,
]
router_llm = get_langchain_llm(GLOBAL_MODEL.chat)
agent = create_openai_tools_agent(router_llm, tool_list, router_prompt)
agent_executor = AgentExecutor(agent=agent, tools=tool_list, verbose=True)

# ===================== 意图预分类（小模型快速判断） =====================

_CLASSIFY_LLM = None

def _get_classify_llm():
    global _CLASSIFY_LLM
    if _CLASSIFY_LLM is None:
        _CLASSIFY_LLM = LLM(GLOBAL_MODEL.small)
    return _CLASSIFY_LLM


def reset_llm_cache():
    """模型配置更新后调用：重建路由 LLM / Agent / 预分类 LLM，使新配置立即生效。"""
    global _CLASSIFY_LLM, router_llm, agent, agent_executor
    _CLASSIFY_LLM = None
    router_llm = get_langchain_llm(GLOBAL_MODEL.chat)
    agent = create_openai_tools_agent(router_llm, tool_list, router_prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tool_list, verbose=True)


def _is_counseling(user_input: str) -> bool:
    """快速预分类：True=心理咨询倾诉，False=工具请求"""
    prompt = (
        """
        你是预分类处理器，严格二分类，仅输出单个大写单词，不能有任何换行、空格、解释、标点。
        可选输出只有两个：COUNSELING / TOOL

        COUNSELING：单纯倾诉心理情绪、人际关系困扰、内心迷茫，无操作指令。
        TOOL：需要执行查询、总结、检索、筛选等操作指令。

        规则：只要要求总结/查找/检索，一律输出TOOL；仅单纯心理倾诉输出COUNSELING
        用户输入：{user_input}
        仅输出一个单词：
        """
    )
    model = _get_classify_llm()
    try:
        resp = model.chat([{"role": "user", "content": prompt}])
        result = "COUNSELING" in (resp or "").upper()
    except Exception as e:
        # 预分类失败降级：按心理咨询线路处理，不中断用户请求
        GLOBAL_TRACKER.add_trace(
            stage="classify_intent",
            label="意图分类失败，降级为心理咨询线路",
            content={"error": str(e), "input": user_input[:80]},
            is_error=True,
            error_msg=str(e)
        )
        return True
    GLOBAL_TRACKER.add_trace(
        stage="classify_intent",
        label="意图分类完成",
        content={"result": "COUNSELING" if result else "TOOL", "input": user_input[:80]}
    )
    return result


# ===================== 内部会话状态（双线模式） =====================
# 心理咨询线路：连续性检测 → 记忆检索 → Agent → 写入full_chat_history
# 工具请求线路：Agent → 直接返回，不写full_chat_history，不触发连续性检测

def agent_service_entry(user_input: str, situation: str = None, role: str = "advisor", mode: str = None) -> Dict[str, Any]:
    """
    对外API统一入口（并发安全包装）：
    - 持有 SESSION_STATE 可重入锁，避免并发请求互相覆盖会话状态；
    - 全程异常兜底：任何 LLM/检索异常转为结构化返回，不再向上抛 500 裸异常。
    """
    with SESSION_STATE.lock:
        try:
            return _agent_service_entry_impl(user_input, situation=situation, role=role, mode=mode)
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


def _agent_service_entry_impl(user_input: str, situation: str = None, role: str = "advisor", mode: str = None) -> Dict[str, Any]:
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

    # ===================== 会话模式：首条锁定 =====================
    if not state.mode:
        if mode in ("direct", "guided"):
            state.mode = mode
        else:
            state.mode = "guided" if role == "guide" else "direct"
        state.save_state()

    # ===================== 引导咨询：直接分发 =====================
    if state.mode == "guided":
        result = guided_reasoning(problem, situation=situation)
        return {
            "intent_type": "guided_reason",
            "reply": result["reply"],
            "ended": result.get("ended", False),
        }
    state.last_role = "advisor"

    # ===================== 1. 构建对话历史（仅含心理咨询对话） =====================
    lc_history = []
    for msg in state.full_chat_history:
        if msg["role"] == "user":
            lc_history.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            lc_history.append(AIMessage(content=msg["content"]))

    # ===================== 2. 预分类：心理咨询 vs 工具请求 =====================
    is_counseling = _is_counseling(problem)

    # ===================== 3. 心理咨询专属：初始化会话 + 记忆检索 =====================
    if is_counseling:
        if not state.session_id:
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
                         "memory_ids": [m.id for m in mems]}
            )
    # ===================== 4. 执行 Agent（所有请求共用） =====================
    routing_input = problem + ("\n【具体情境】\n" + situation if situation else "")
    invoke_kwargs = {"input": routing_input, "chat_history": lc_history}
    res = agent_executor.invoke(invoke_kwargs)
    raw_output = res["output"]

    # ===================== 5. 仅心理咨询写入 full_chat_history =====================
    if is_counseling and "【心理咨询回复】" in raw_output:
        state.full_chat_history.append({"role": "user", "content": problem})
        state.full_chat_history.append({"role": "assistant", "content": raw_output, "speaker": "advisor"})
        state.last_consult_query = problem
        state.save_state()
        GLOBAL_TRACKER.add_trace(
            stage="session_save",
            label="心理咨询回复完成，会话状态已保存",
            content={"dialogue_turns": len(state.full_chat_history),
                     "referenced_docs": len(state.referenced_doc_ids),
                     "similar_memories": len(state.similar_memories),
                     "session_id": state.session_id}
        )
    # ===================== 6. 解析返回 =====================
    if "【心理咨询回复】" in raw_output:
        pure = raw_output.split("【心理咨询回复】")[-1]
        return {
            "intent_type": "psychological_consult",
            "reply": pure.strip(),
            "raw_tool_output": raw_output,
        }

    if "【引导提问】" in raw_output:
        pure = raw_output.split("【引导提问】")[-1]
        return {
            "intent_type": "guided_reason",
            "reply": pure.strip(),
        }

    if "【模糊筛选匹配结果】" in raw_output:
        pure = raw_output.split("【模糊筛选匹配结果】")[-1]
        return {
            "intent_type": "meta_filter",
            "reply": pure.strip(),
            "raw_tool_output": raw_output,
        }
    elif "【精准文本匹配结果】" in raw_output:
        pure = raw_output.split("【精准文本匹配结果】")[-1]
        return {
            "intent_type": "precise_text_filter",
            "reply": pure.strip(),
            "raw_tool_output": raw_output,
        }
    elif "【记忆搜索结果】" in raw_output:
        pure = raw_output.split("【记忆搜索结果】")[-1]
        return {
            "intent_type": "search_memory",
            "reply": pure.strip(),
        }
    elif "【精准记忆筛选结果】" in raw_output:
        pure = raw_output.split("【精准记忆筛选结果】")[-1]
        return {
            "intent_type": "precise_memory_filter",
            "reply": pure.strip(),
        }
    elif "【会话总结" in raw_output:
        pure = raw_output.split("【会话总结")[-1]
        full_text = "【会话总结" + pure
        return {
            "intent_type": "summarize_memory",
            "reply": pure.strip(),
            "raw_tool_output": full_text,
        }
    else:
        return {"intent_type": "other", "reply": raw_output, "raw_tool_output": raw_output}