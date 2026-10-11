from typing import Optional, List, Union, Dict, Any
from datetime import datetime
from dataclasses import asdict

from langchain_core.tools import tool

from config.prompt_config import guide_system_prompt, guide_human_prompt
from core.helper.knowledge_cache import KNOWLEDGE_CACHE
from core.helper.memory_cache import MEMORY_CACHE
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.meta_db.context_meta import SESSION_STATE
from core.embedding.embedding import EmbeddingModel
from core.embedding.embedding_memory import MemoryEmbedding
from core.loader.knowledge_loader import KnowledgeLoader
from core.helper.prompt_optimizer import PromptOptimizer
from core.helper.reranker import Reranker
from core.schema import Memory
from config.model_config import EMBEDDING_MODEL, GLOBAL_MODEL, RERANKING_MODEL
from config.path_config import MEMORY_VECTOR_DB_DIR, MEMORY_COLLECTION_NAME, MEMORY_META_DB_PATH, MEMORY_DIR, \
    META_DB_PATH, VECTOR_DB_DIR, COLLECTION_NAME, BM25_PATH
from core.helper.BM25 import BM25TagIndexer
from core.helper.RAG_agent import PsychRAGAgent, format_principle, format_experience
from core.llm import LLM
from core.helper.retriever import Retriever
from core.vector_db.documents_vector_db import VectorDB
from core.vector_db.memory_vector_db import MemoryVectorDB
from core.meta_db.memory_meta import MemoryMetaDB
from core.helper.session_summarizer import SessionSummarizer
from config.topic_config import search_topic, VALID_TOPICS
from core.meta_db.knowledge_meta import KnowledgeMetaDB

# ===================== Lazy init: memory infrastructure =====================
_GLOBAL_MEMORY_EMBEDDING = None
_GLOBAL_MEMORY_VECTOR_DB = None
_GLOBAL_MEMORY_META_DB = None
_GLOBAL_MEMORY_SUMMARIZER = None
_GLOBAL_RAG_AGENT = None

def _get_memory_embedding():
    global _GLOBAL_MEMORY_EMBEDDING
    if _GLOBAL_MEMORY_EMBEDDING is None:
        _GLOBAL_MEMORY_EMBEDDING = MemoryEmbedding(EMBEDDING_MODEL)
    return _GLOBAL_MEMORY_EMBEDDING


def _get_memory_vector_db():
    global _GLOBAL_MEMORY_VECTOR_DB
    if _GLOBAL_MEMORY_VECTOR_DB is None:
        _GLOBAL_MEMORY_VECTOR_DB = MemoryVectorDB(MEMORY_VECTOR_DB_DIR, MEMORY_COLLECTION_NAME)
    return _GLOBAL_MEMORY_VECTOR_DB


def _get_memory_meta_db():
    global _GLOBAL_MEMORY_META_DB
    if _GLOBAL_MEMORY_META_DB is None:
        _GLOBAL_MEMORY_META_DB = MemoryMetaDB(str(MEMORY_META_DB_PATH))
    return _GLOBAL_MEMORY_META_DB

def _get_memory_summarizer():
    global _GLOBAL_MEMORY_SUMMARIZER
    if _GLOBAL_MEMORY_SUMMARIZER is None:
        model = LLM(GLOBAL_MODEL.large)
        _GLOBAL_MEMORY_SUMMARIZER = SessionSummarizer(model)
    return _GLOBAL_MEMORY_SUMMARIZER

def get_global_rag_agent():
    global _GLOBAL_RAG_AGENT
    if _GLOBAL_RAG_AGENT is None:
        embedding_model = EmbeddingModel(EMBEDDING_MODEL)
        vector_db = VectorDB(VECTOR_DB_DIR, COLLECTION_NAME)
        indexer = BM25TagIndexer(documents=[], bm25_path=BM25_PATH, topic_weight=3, keyword_weight=1)
        model = LLM(GLOBAL_MODEL.small)
        prompt_optimizer = PromptOptimizer(model)
        knowledge_loader = KnowledgeLoader()
        reranker = Reranker(RERANKING_MODEL)
        retriever = Retriever(embedding_model, vector_db, indexer, prompt_optimizer, knowledge_loader, reranker)
        _GLOBAL_RAG_AGENT = PsychRAGAgent(retriever)
    return _GLOBAL_RAG_AGENT

meta_db = KnowledgeMetaDB(META_DB_PATH)

def has_any_filter(*args) -> bool:
    """判断是否存在任意有效筛选条件，全为None返回False"""
    for arg in args:
        if arg is None:
            continue
        if isinstance(arg, (list, tuple)):
            if any(str(x).strip() for x in arg):
                return True
        elif str(arg).strip() != "":
            return True
    return False


def resolve_topics(topic_keyword) -> Optional[List[str]]:
    """主题关键词（单个字符串或列表）→ 标准英文主题标签列表，OR 语义。"""
    if topic_keyword is None:
        return None
    items = [topic_keyword] if isinstance(topic_keyword, str) else list(topic_keyword)
    resolved = []
    for kw in items:
        k = str(kw).strip()
        if not k:
            continue
        if k in VALID_TOPICS:
            resolved.append(k)
        else:
            t = search_topic(k)
            if t:
                resolved.append(t)
    return resolved or None


def to_list(v) -> Optional[List[str]]:
    """兼容单值/多值入参，归一化为非空字符串列表；空返回 None。"""
    if v is None:
        return None
    if isinstance(v, str):
        items = [v]
    elif isinstance(v, (list, tuple)):
        items = list(v)
    else:
        items = [v]
    cleaned = [str(x).strip() for x in items if x is not None and str(x).strip()]
    return cleaned or None


def generate_session_id() -> str:
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    mem_dir = MEMORY_DIR
    if mem_dir.exists():
        existing = [f.stem for f in mem_dir.glob(f"session_{date_str}_*.json")]
        max_n = 0
        for e in existing:
            try:
                n = int(e.rsplit("_", 1)[-1])
                max_n = max(max_n, n)
            except ValueError:
                pass
        seq = max_n + 1
    else:
        seq = 1
    return f"session_{date_str}_{seq:03d}"


def search_related_memories(query: str, top_k: int = 3) -> List[Memory]:
    """Search memory vector DB for similar past sessions. Returns Memory list."""
    embedding_model = _get_memory_embedding()
    vec_db = _get_memory_vector_db()

    if vec_db.count() == 0:
        return []

    emb = embedding_model.encode(query)
    hit_ids = vec_db.query(emb, top_k=top_k)

    if not hit_ids:
        return []

    all_memories = MEMORY_CACHE.memories
    id_to_memory = {m.id: m for m in all_memories}
    results = [id_to_memory[mid] for mid in hit_ids if mid in id_to_memory]
    return results


def _format_memories_for_prompt(memories: List[Memory]) -> str:
    if not memories:
        return "暂无相关历史会话记录"
    blocks = []
    for idx, m in enumerate(memories, 1):
        block = f"【历史会话{idx}】ID:{m.id}\n"
        block += f"主题：{m.title}\n"
        block += f"时间：{m.start_time} ~ {m.end_time}\n"
        block += f"概要：{m.summary}\n"
        if m.insights:
            block += f"核心洞察：{'；'.join(m.insights)}\n"
        if m.keywords:
            block += f"关键词：{', '.join(m.keywords)}\n"
        blocks.append(block)
    return "\n---\n".join(blocks)


def _format_chat_history(chat_history: List[dict]) -> str:
    """格式化当前会话对话历史（本轮之前的 user/assistant 轮次）。"""
    if not chat_history:
        return "暂无当前会话对话历史"
    lines = []
    for msg in chat_history:
        role = "用户" if msg.get("role") == "user" else "咨询师"
        lines.append(f"{role}：{msg.get('content', '')}")
    return "\n".join(lines)


def _format_guided_reasons(guided_reasons: List[dict]) -> str:
    """格式化引导推理问答链 [{role:'guide'|'user', content}] 为文本。"""
    if not guided_reasons:
        return "暂无已完成推理"
    lines = []
    for msg in guided_reasons:
        role = "引导者" if msg.get("role") == "guide" else "用户"
        lines.append(f"{role}：{msg.get('content', '')}")
    return "\n".join(lines)


_GLOBAL_GUIDE_LLM = None


def _get_guide_llm():
    global _GLOBAL_GUIDE_LLM
    if _GLOBAL_GUIDE_LLM is None:
        _GLOBAL_GUIDE_LLM = LLM(GLOBAL_MODEL.chat)
    return _GLOBAL_GUIDE_LLM

def reset_llm_cache():
    """模型配置更新后调用：清空所有惰性缓存的模型 / Agent 实例，使新配置立即生效。"""
    global _GLOBAL_MEMORY_SUMMARIZER, _GLOBAL_RAG_AGENT, _GLOBAL_GUIDE_LLM
    _GLOBAL_MEMORY_SUMMARIZER = None
    _GLOBAL_RAG_AGENT = None
    _GLOBAL_GUIDE_LLM = None


def _auto_advise(problem: str, situation: str) -> str:
    """引导结束后自动生成建议报告：复用链首检索的文档与记忆，不触发二次检索。"""
    state = SESSION_STATE
    mem_ctx = _format_memories_for_prompt(state.similar_memories)
    chat_ctx = _format_chat_history(state.full_chat_history)
    reasons_ctx = _format_guided_reasons(state.guided_reasons)
    docs = KNOWLEDGE_CACHE.get_by_ids(list(state.referenced_doc_ids))
    try:
        answer = get_global_rag_agent().rag_chain.invoke({
            "docs": docs,
            "query": problem,
            "situation": situation,
            "memory_context": mem_ctx,
            "chat_history": chat_ctx,
            "guided_reasons": reasons_ctx,
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
        docs = get_global_rag_agent().retriever.retrieve(user_input, 6, 3)
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

    prompt = guide_human_prompt.format(
        problem_context=problem_ctx,
        user_input=user_input,
        chat_history=chat_ctx,
        memory_context=memory_ctx,
        knowledge_context=knowledge_ctx,
        guided_reasons=reasons_ctx,
    )
    try:
        raw = _get_guide_llm().chat([
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


def meta_filter(
    doc_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    topic_keyword: Optional[Union[str, List[str]]] = None,
    keyword: Optional[Union[str, List[str]]] = None,
    emotion: Optional[Union[str, List[str]]] = None,
) -> List[dict]:
    """知识文档元数据过滤，返回结构化文档列表。"""
    GLOBAL_TRACKER.add_trace(
        stage="tool_call",
        label="meta_filter 查询",
        content={"doc_type": doc_type, "start_date": start_date, "end_date": end_date,
                 "topic_keyword": topic_keyword, "keyword": keyword, "emotion": emotion}
    )

    if not has_any_filter(doc_type, start_date, end_date, topic_keyword, keyword, emotion):
        GLOBAL_TRACKER.add_trace(
            stage="tool_result",
            label="meta_filter 拦截: 未传入任何筛选条件",
            content={"hit_count": 0}
        )
        return []

    topic_like = resolve_topics(topic_keyword)
    if topic_keyword and topic_like is None:
        GLOBAL_TRACKER.add_trace(
            stage="tool_result",
            label="meta_filter 结果: 主题无匹配",
            content={"hit_count": 0}
        )
        return []

    hit_ids = meta_db.filter_meta(
        doc_type=doc_type,
        start_date=start_date,
        end_date=end_date,
        topic_like=topic_like,
        keyword_like=to_list(keyword),
        primary_emotion=to_list(emotion),
    )
    docs = KNOWLEDGE_CACHE.get_by_ids(hit_ids)
    GLOBAL_TRACKER.add_trace(
        stage="tool_result",
        label="meta_filter 结果",
        content={"hit_count": len(docs), "doc_ids": [d.doc_id for d in docs]}
    )
    return [asdict(d) for d in docs]


def precise_text_filter(
    target_text: str,
    doc_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    topic_keyword: Optional[Union[str, List[str]]] = None,
    keyword: Optional[Union[str, List[str]]] = None,
    emotion: Optional[Union[str, List[str]]] = None,
) -> List[dict]:
    """知识文档精准全文匹配 + 元过滤，返回结构化文档列表。"""
    GLOBAL_TRACKER.add_trace(
        stage="tool_call",
        label="precise_text_filter 查询",
        content={"target_text": target_text, "doc_type": doc_type,
                 "start_date": start_date, "end_date": end_date, "topic_keyword": topic_keyword,
                 "keyword": keyword, "emotion": emotion}
    )

    if target_text is None or str(target_text).strip() == "":
        GLOBAL_TRACKER.add_trace(
            stage="tool_result",
            label="precise_text_filter 拦截: 精准匹配文本为空",
            content={"hit_count": 0}
        )
        return []

    topic_like = resolve_topics(topic_keyword)
    if topic_keyword and topic_like is None:
        GLOBAL_TRACKER.add_trace(
            stage="tool_result",
            label="precise_text_filter 结果: 主题无匹配",
            content={"hit_count": 0}
        )
        return []

    hit_ids = meta_db.filter_meta(
        doc_type=doc_type,
        start_date=start_date,
        end_date=end_date,
        topic_like=topic_like,
        keyword_like=to_list(keyword),
        primary_emotion=to_list(emotion),
    )
    candidates = KNOWLEDGE_CACHE.get_by_ids(hit_ids)
    target = str(target_text)
    match = [d for d in candidates if target in (d.summary + d.content)]
    GLOBAL_TRACKER.add_trace(
        stage="tool_result",
        label="precise_text_filter 结果",
        content={"target_text": target, "hit_count": len(match), "doc_ids": [d.doc_id for d in match]}
    )
    return [asdict(d) for d in match]


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

        summarizer = _get_memory_summarizer()
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

        embedding_model = _get_memory_embedding()
        vec_db = _get_memory_vector_db()
        meta_db_ = _get_memory_meta_db()
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
    meta_db_mem = _get_memory_meta_db()
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


@tool
def psychological_consult_tool(user_input: str):
    """
    【心理咨询工具】处理用户情绪倾诉、内心迷茫，连贯心理对话
    Args:
        user_input: 用户当前倾诉
    历史记忆由工具内部从全局会话状态读取，无需路由Agent传入。
    """
    memory_text = _format_memories_for_prompt(SESSION_STATE.similar_memories)
    chat_text = _format_chat_history(SESSION_STATE.full_chat_history)
    reasons_text = _format_guided_reasons(SESSION_STATE.guided_reasons)
    GLOBAL_TRACKER.add_trace(
        stage="tool_call",
        label="调用工具: psychological_consult_tool",
        content={"user_input": user_input[:100],
                 "has_memories": bool(memory_text and memory_text != "暂无相关历史会话记录"),
                 "has_chat_history": bool(SESSION_STATE.full_chat_history)}
    )
    rag_agent = get_global_rag_agent()
    try:
        result = rag_agent.chat(user_input, memory_context=memory_text, chat_history=chat_text, guided_reasons=reasons_text)
    except Exception as e:
        GLOBAL_TRACKER.add_trace(
            stage="tool_result",
            label="psychological_consult_tool 异常（已兜底）",
            content={"error": str(e), "user_input": user_input[:80]},
            is_error=True,
            error_msg=str(e)
        )
        return f"【心理咨询回复】\n抱歉，检索或生成服务暂时不可用：{e}"
    doc_ids = result['raw']['doc_ids']
    SESSION_STATE.referenced_doc_ids.update(doc_ids)
    GLOBAL_TRACKER.add_trace(
        stage="tool_result",
        label="psychological_consult_tool 完成",
        content={"referenced_docs": doc_ids,
                 "principle_count": result['raw']['principle_count'],
                 "experience_count": result['raw']['experience_count']}
    )
    return f"【心理咨询回复】\n{result['answer']}"


@tool
def meta_filter_tool(
    doc_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    topic_keyword: Optional[str] = None,
    keyword: Optional[str] = None,
    emotion: Optional[str] = None,
) -> str:
    """
    【模糊筛选工具】基于元数据topic/关键词/日期/情绪宽泛匹配文档
    使用场景：用户要某一类主题、某时间段、某种情绪的所有文章，不要求精确包含某段文字
    Args:
        doc_type: daily / weekly / None全部
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        topic_keyword: 主题英文标签或中文关键词模糊检索
        keyword: 文档关键词模糊匹配
        emotion: 情绪英文标签如Anxiety
    """
    docs = meta_filter(
        doc_type=doc_type,
        start_date=start_date,
        end_date=end_date,
        topic_keyword=topic_keyword,
        keyword=keyword,
        emotion=emotion
    )
    if not docs:
        return "未匹配到任何符合条件的文档"
    output = "【模糊筛选匹配结果】\n"
    for idx, d in enumerate(docs, 1):
        if d.get("doc_type") == "weekly":
            output += f"{idx}. 类型:weekly 问题:{d.get('problem','')} 分析:{d.get('analysis','')} 解决方案:{d.get('solution','')}\n"
        else:
            output += f"{idx}. 类型:daily 原文档:{d.get('content','')}\n"
    return output


@tool
def precise_text_filter_tool(
    target_text: str,
    doc_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    topic_keyword: Optional[str] = None,
    keyword: Optional[str] = None,
    emotion: Optional[str] = None,
) -> str:
    """
    【精准文本筛选工具】查找正文/摘要中精确包含target_text的文档
    使用场景：用户明确要求找出 "写到XX、包含XX文字" 的记录
    Args:
        target_text: 需要精确匹配的原文短句
        doc_type: daily / weekly
        start_date: 起始日期
        end_date: 结束日期
        topic_keyword: 前置缩小范围的主题关键词
        keyword: 文档关键词模糊匹配
        emotion: 情绪英文标签如Anxiety
    """
    docs = precise_text_filter(
        target_text=target_text,
        doc_type=doc_type,
        start_date=start_date,
        end_date=end_date,
        topic_keyword=topic_keyword,
        keyword=keyword,
        emotion=emotion
    )
    if not docs:
        return f"没有文档精确包含文字：{target_text}"
    output = "【精准文本匹配结果】\n"
    output += f"（包含「{target_text}」）\n"
    for idx, d in enumerate(docs, 1):
        if d.get("doc_type") == "weekly":
            output += f"{idx}. 类型:weekly 问题:{d.get('problem','')} 分析:{d.get('analysis','')} 解决方案:{d.get('solution','')}\n"
        else:
            output += f"{idx}. 类型:daily 原文档:{d.get('content','')}\n"
    return output


@tool
def summarize_memory_tool() -> str:
    """
    【会话总结工具】读取内存当前完整对话，生成记忆并后台持久化
    使用场景：用户明确要求"总结我们的对话""保存这次聊天""记住这次讨论"等
    无需传入参数，自动读取全局会话缓存
    """
    return summarize_memory()


@tool
def search_memory_tool(query: str, top_k: int = 3) -> str:
    """
    【记忆搜索工具】在历史会话记忆中搜索与query最相似的过往对话
    使用场景：用户提到"之前聊过XX""回顾关于XX的讨论""上次讨论的XX"
    Args:
        query: 搜索查询文本
        top_k: 返回条数，默认3
    """
    memories = search_memory(query, top_k)
    if not memories:
        return "【记忆搜索结果】未找到相关历史会话记录"
    output = "【记忆搜索结果】\n"
    for idx, m in enumerate(memories, 1):
        output += (
            f"{idx}. [{m.get('id','')}] {m.get('title','')}\n"
            f"   时间：{m.get('start_time','')} ~ {m.get('end_time','')}\n"
            f"   概要：{m.get('summary','')}\n"
        )
        if m.get("insights"):
            output += f"   洞察：{'；'.join(m.get('insights', []))}\n"
        output += "\n"
    return output


@tool
def precise_memory_filter_tool(
    topic_keyword: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    keyword: Optional[str] = None,
    emotion: Optional[str] = None,
) -> str:
    """
    【精准记忆筛选工具】基于元数据精确筛选历史会话记忆
    使用场景：用户明确要求"列出关于焦虑的历史对话""7月份聊过哪些话题"
    Args:
        topic_keyword: 主题关键词
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        keyword: 对话关键词模糊匹配
        emotion: 情绪英文标签
    """
    memories = precise_memory_filter(
        topic_keyword=topic_keyword,
        start_date=start_date,
        end_date=end_date,
        keyword=keyword,
        emotion=emotion)
    if not memories:
        return "【精准记忆筛选结果】未匹配到任何历史会话记录"
    output = "【精准记忆筛选结果】\n"
    for idx, m in enumerate(memories, 1):
        output += (
            f"{idx}. [{m.get('id','')}] {m.get('title','')}\n"
            f"   时间：{m.get('start_time','')} ~ {m.get('end_time','')}\n"
            f"   概要：{m.get('summary','')}\n"
        )
        if m.get("insights"):
            output += f"   洞察：{'；'.join(m.get('insights', []))}\n"
        output += "\n"
    return output
