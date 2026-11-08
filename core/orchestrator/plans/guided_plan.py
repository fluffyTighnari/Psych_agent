# -*- coding: utf-8 -*-
"""引导咨询计划（guided plan）：引导问答链编排。

阶段 3-C 从 core/tools/guided.py 迁入——它是完整的引导编排流程
（链首检索锚定 → 引导问答循环 → 【结束】后自动生成建议报告），
属于编排层而非工具原语。仍依赖全局 SESSION_STATE（阶段 5 多会话时随 Session 显式传入）。
"""
from typing import Dict, Any
from config.prompt_config import guide_system_prompt, guide_human_prompt
from core.meta_db.context_meta import SESSION_STATE
from core.helper.knowledge_cache import KNOWLEDGE_CACHE
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.helper.RAG_agent import format_principle, format_experience
from core.infra.context import get_app_context
from core.tools.primitives import (
    generate_session_id, search_related_memories,
    _format_memories_for_prompt, _format_chat_history, _format_guided_reasons,
    format_attached_context,
)


def _auto_advise(problem: str, situation: str) -> str:
    """引导结束后自动生成建议报告：复用链首检索的文档与记忆，不触发二次检索。"""
    state = SESSION_STATE
    mem_ctx = _format_memories_for_prompt(state.similar_memories)
    chat_ctx = _format_chat_history(state.full_chat_history)
    reasons_ctx = _format_guided_reasons(state.guided_reasons)
    docs = KNOWLEDGE_CACHE.get_by_ids(list(state.referenced_doc_ids))
    try:
        answer = get_app_context().rag_agent().rag_chain.invoke({
            "docs": docs,
            "query": problem,
            "situation": situation,
            "memory_context": mem_ctx,
            "chat_history": chat_ctx,
            "guided_reasons": reasons_ctx,
            "attached_context": format_attached_context(state.attachments),
        })
    except Exception as e:
        GLOBAL_TRACKER.add_trace(
            stage="guided_reasoning",
            label="建议报告生成失败（已兜底）",
            content={"error": str(e)},
            is_error=True,
            error_msg=str(e)
        )
        return "（自动生成建议报告失败，请稍后重试）"
    GLOBAL_TRACKER.add_trace(
        stage="guided_reasoning",
        label="引导结束自动生成建议报告",
        content={"referenced_docs": list(state.referenced_doc_ids),
                 "principle_count": len([d for d in docs if d.doc_type == "weekly"]),
                 "experience_count": len([d for d in docs if d.doc_type == "daily"])}
    )
    return answer


def guided_reasoning(user_input: str, situation: str = "", anchor_problem: str = None) -> Dict[str, Any]:
    """自我推理引导者：链首检索一次并锚定核心问题；【结束】后自动生成建议报告。"""
    state = SESSION_STATE
    new_chain = not state.guided_reasons or state.guided_ended

    GLOBAL_TRACKER.add_trace(
        stage="guided_reasoning",
        label="引导推理" + ("（新链，触发检索）" if new_chain else "（回答引导问题，跳过检索）"),
        content={"new_chain": new_chain, "user_input": user_input[:100], "situation": situation[:100]}
    )

    if new_chain:
        state.guided_reasons = []
        state.guided_ended = False
        if not state.session_id:
            state.session_id = generate_session_id()
        state.mode_problem = anchor_problem or user_input
        state.mode_situation = situation
        state.similar_memories = search_related_memories(user_input)
        docs = get_app_context().rag_agent().pipeline.retrieve_documents(user_input)
        state.referenced_doc_ids = set(d.doc_id for d in docs)
        GLOBAL_TRACKER.add_trace(
            stage="guided_reasoning",
            label="引导新链检索完成",
            content={"session_id": state.session_id,
                     "memory_count": len(state.similar_memories),
                     "doc_ids": list(state.referenced_doc_ids)}
        )

    problem_ctx = f"核心问题：{state.mode_problem}"
    if state.mode_situation:
        problem_ctx += f"\n具体情境：{state.mode_situation}"

    memory_ctx = _format_memories_for_prompt(state.similar_memories)
    docs = KNOWLEDGE_CACHE.get_by_ids(list(state.referenced_doc_ids))
    knowledge_ctx = format_principle(docs) + "\n\n" + format_experience(docs)
    reasons_ctx = _format_guided_reasons(state.guided_reasons)
    chat_ctx = _format_chat_history(state.full_chat_history)

    # 用户主动引用的资料：引导者应围绕用户的疑惑推进，而不是无视引用另起话题
    attached_ctx = format_attached_context(state.attachments)

    prompt = guide_human_prompt.format(
        problem_context=problem_ctx,
        user_input=user_input,
        chat_history=chat_ctx,
        memory_context=memory_ctx,
        knowledge_context=knowledge_ctx,
        guided_reasons=reasons_ctx,
        attached_context=attached_ctx,
    )
    try:
        raw = get_app_context().guide_llm().chat([
            {"role": "system", "content": guide_system_prompt},
            {"role": "user", "content": prompt}
        ]).strip()
    except Exception as e:
        # 引导模型不可用时返回友好错误，不中断请求（状态将在下次新链自动重置）
        GLOBAL_TRACKER.add_trace(
            stage="guided_reasoning",
            label="引导模型调用失败（已兜底）",
            content={"error": str(e), "user_input": user_input[:80]},
            is_error=True,
            error_msg=str(e)
        )
        return {"reply": "引导服务暂时不可用，请稍后重试", "ended": False}

    GLOBAL_TRACKER.add_trace(
        stage="guided_reasoning",
        label="引导模型原始输出",
        content={"raw": raw[:300]}
    )

    ended = raw.startswith("【结束】")
    reply = raw[4:].strip() if ended else raw

    if not new_chain:
        state.guided_reasons.append({"role": "user", "content": user_input})
    state.guided_reasons.append({"role": "guide", "content": reply})
    state.full_chat_history.append({"role": "user", "content": user_input})
    state.full_chat_history.append({"role": "assistant", "content": reply, "speaker": "guide"})

    if ended:
        state.guided_ended = True
        report = _auto_advise(state.mode_problem, state.mode_situation)
        state.full_chat_history.append({"role": "assistant", "content": report, "speaker": "advisor"})
        state.last_consult_query = state.mode_problem
        state.save_state()
        return {"reply": f"{reply}\n\n【建议总结】\n{report}", "ended": True}

    state.last_consult_query = user_input
    state.save_state()
    pair_index = (len(state.guided_reasons) - 1) // 2
    return {"reply": f"{reply}\n\n[[guide:reason_{pair_index}]]", "ended": False}
