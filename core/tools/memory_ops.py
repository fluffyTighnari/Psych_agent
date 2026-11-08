# -*- coding: utf-8 -*-
"""记忆操作原语：会话总结落库 / 记忆语义检索 / 记忆元数据过滤。"""
from typing import Optional, List, Union
from dataclasses import asdict
from core.meta_db.context_meta import SESSION_STATE
from core.helper.memory_cache import MEMORY_CACHE
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.infra.context import get_app_context
from core.tools.primitives import search_related_memories, resolve_topics, to_list


def summarize_memory() -> str:
    GLOBAL_TRACKER.add_trace(
        stage="tool_call",
        label="调用工具: summarize_memory_tool",
        content={}
    )
    try:
        state = SESSION_STATE
        dialogues = state.full_chat_history
        ref_docs = list(state.referenced_doc_ids)
        session_id = state.session_id

        if not dialogues:
            GLOBAL_TRACKER.add_trace(
                stage="tool_result",
                label="summarize_memory_tool: 无对话历史",
                content={}
            )
            return "【会话总结】当前无对话历史，无法总结"

        summarizer = get_app_context().memory_summarizer()
        memory = summarizer.summarize(
            session_id=session_id,
            chat_history=dialogues,
            referenced_documents=ref_docs,
            guided_reasons=state.guided_reasons,
        )
        if memory is None:
            GLOBAL_TRACKER.add_trace(
                stage="tool_result",
                label="summarize_memory_tool: 总结失败",
                content={},
                is_error=True,
                error_msg="LLM总结返回None"
            )
            return "【会话总结】LLM总结失败，请重试"

        GLOBAL_TRACKER.add_trace(
            stage="tool_result",
            label="summarize_memory_tool 完成",
            content={"memory_id": memory.id, "title": memory.title, "dialogue_count": len(dialogues)}
        )

        embedding_model = get_app_context().memory_embedding()
        vec_db = get_app_context().memory_vector_db()
        meta_db_ = get_app_context().memory_meta_db()
        emb = embedding_model.encode(memory.summary)

        # 语义关联：总结时检索 top-k 最相似历史记忆写入 related_memory
        related_ids = []
        if vec_db.count() > 0:
            related_ids = vec_db.query(emb, top_k=3)
        memory.related_memory = related_ids
        # 注意：memory JSON 已在 summarize() 内部写盘（_write_memory_json），此处不重复写

        vec_db.upsert_memories([memory], [emb])
        meta_db_.upsert(memory)

        # 写入即生效：刷新内存记忆缓存，网页历史记忆无需重启即可看到新记录
        try:
            MEMORY_CACHE.reload()
        except Exception as e:
            GLOBAL_TRACKER.add_trace(
                stage="summarize_memory",
                label="记忆缓存刷新失败（不影响已持久化数据）",
                content={"error": str(e)},
                is_error=True,
                error_msg=str(e)
            )

        state.full_chat_history.clear()
        state.similar_memories.clear()
        state.referenced_doc_ids.clear()
        state.guided_reasons.clear()
        state.last_consult_query = ""
        state.session_id = ""
        state.mode = ""
        state.mode_problem = ""
        state.mode_situation = ""
        state.guided_ended = False
        state.save_state()

        GLOBAL_TRACKER.add_trace(
            stage="summarize_memory",
            label="记忆向量与元数据持久化完成",
            content={"session_id": session_id, "vector_db_count": vec_db.count()}
        )

        return (
            f"【会话总结完成】\n"
            f"记忆ID：{memory.id}\n"
            f"标题：{memory.title}\n"
            f"概要：{memory.summary}\n"
            f"核心洞察：{'；'.join(memory.insights) if memory.insights else '无'}"
        )
    except Exception as e:
        GLOBAL_TRACKER.add_trace(
            stage="tool_result",
            label="summarize_memory_tool 异常",
            content={},
            is_error=True,
            error_msg=str(e)
        )
        return f"【会话总结失败】{str(e)}"


def search_memory(query: str, top_k: int = 3) -> List[dict]:
    """记忆向量语义检索，返回结构化记忆列表。"""
    GLOBAL_TRACKER.add_trace(
        stage="tool_call",
        label="search_memory 查询",
        content={"query": query[:100], "top_k": top_k}
    )
    memories = search_related_memories(query, top_k=top_k)
    GLOBAL_TRACKER.add_trace(
        stage="tool_result",
        label="search_memory 结果",
        content={"hit_count": len(memories), "memory_ids": [m.id for m in memories]}
    )
    return [asdict(m) for m in memories]


def precise_memory_filter(
    topic_keyword: Optional[Union[str, List[str]]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    keyword: Optional[Union[str, List[str]]] = None,
    emotion: Optional[Union[str, List[str]]] = None,
) -> List[dict]:
    """历史记忆元数据精准过滤，返回结构化记忆列表。"""
    GLOBAL_TRACKER.add_trace(
        stage="tool_call",
        label="precise_memory_filter 查询",
        content={"topic_keyword": topic_keyword, "start_date": start_date,
                 "end_date": end_date, "keyword": keyword, "emotion": emotion}
    )
    meta_db_mem = get_app_context().memory_meta_db()
    hit_ids = meta_db_mem.filter_memories(
        start_date=start_date,
        end_date=end_date,
        topic_like=resolve_topics(topic_keyword),
        keyword_like=to_list(keyword),
        primary_emotion=to_list(emotion),
    )
    all_memories = MEMORY_CACHE.memories
    id_to_memory = {m.id: m for m in all_memories}
    results = [id_to_memory[mid] for mid in hit_ids if mid in id_to_memory]
    GLOBAL_TRACKER.add_trace(
        stage="tool_result",
        label="precise_memory_filter 结果",
        content={"hit_count": len(results), "memory_ids": [m.id for m in results]}
    )
    return [asdict(m) for m in results]