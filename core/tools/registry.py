# -*- coding: utf-8 -*-
"""LangChain @tool 壳层：把纯函数结果格式化为 LLM 可读字符串，注册进 Agent。"""
from typing import Optional, List, Union
from langchain_core.tools import tool
from core.meta_db.context_meta import SESSION_STATE
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.infra.context import get_app_context
from core.tools.primitives import (
    _format_memories_for_prompt, _format_chat_history, _format_guided_reasons,
    format_attached_context,
)
from core.tools.knowledge import meta_filter, precise_text_filter
from core.tools.memory_ops import summarize_memory, search_memory, precise_memory_filter
from core.helper.RAG_agent import format_principle, format_experience
from core.meta_db.knowledge_meta import _normalize_date


@tool
def retrieve_knowledge_tool(query: str) -> str:
    """
    【知识检索工具】在用户沉淀的心理原则（周记）与过往经历（日记）中，检索与当前核心困扰最相关的知识证据，供随后的心理咨询回复参考。
    使用场景：用户在寻求具体的心理理解、方法、视角或"怎么办"，需要结合他自己沉淀的原则/经历再回应时，先调用本工具拿到证据，再调 psychological_consult_tool。
    不适用：纯情绪承接、简短回应、追问澄清、确认、寒暄等轮次（直接调 psychological_consult_tool 自然回应，无需检索）。
    Args:
        query: 最能概括用户核心困扰的检索短语，去掉寒暄与具体情境细节
    """
    state = SESSION_STATE
    # 硬 Budget（代码层）：单轮最多检索 2 次，超出即拦截并降级为直接 consult
    if state.retrieve_budget_left <= 0:
        GLOBAL_TRACKER.add_trace(
            stage="tool_result",
            label="retrieve_knowledge_tool 预算已用尽（硬限制）",
            content={"budget_left": state.retrieve_budget_left},
        )
        return ("【知识检索证据】本轮检索预算已用尽（单轮最多检索 2 次）。"
                "请基于已有证据直接调用 psychological_consult_tool 产出最终回复，"
                "不要再尝试检索。")
    state.retrieve_budget_left -= 1
    rag_agent = get_app_context().rag_agent()

    # 延迟 import：core.tools 包初始化与 core.orchestrator（executor 反向依赖 core.tools）
    # 存在包级循环，放在函数内可彻底避开 import 期耦合。
    from core.orchestrator.evaluator import evaluate_evidence, EVIDENCE_GAP
    from core.orchestrator.remediation import remediate_once, merge_evidence

    try:
        result = rag_agent.retrieve_scored(query)
    except Exception as e:
        GLOBAL_TRACKER.add_trace(
            stage="tool_result",
            label="retrieve_knowledge_tool 检索异常（已兜底）",
            content={"error": str(e), "query": query[:80]},
            is_error=True,
            error_msg=str(e)
        )
        return ("【知识检索证据】检索服务暂时不可用。请直接调用 psychological_consult_tool，"
                "基于你的理解与对话上下文自然回应，不要把本提示原文发给用户。")

    docs = result.get("docs") or []
    scores = result.get("scores") or {}
    evidence = evaluate_evidence(docs, scores, query=query)
    remediation = None

    # CRAG 纠正：只在 grade=evidence_gap 时执行一次；预算不足 / 已补过则自动跳过。
    if evidence["status"] == EVIDENCE_GAP:
        remediation = remediate_once(rag_agent, result.get("query") or query,
                                     evidence["reason"], state)
        if remediation.get("docs"):
            docs, scores = merge_evidence(docs, scores,
                                          remediation["docs"], remediation["scores"])
            # 用补救后的证据重新分级（仍 gap 表示「补了也不足」，直接接受，不再补）
            evidence = evaluate_evidence(docs, scores, query=query)
        evidence["remediation_action"] = remediation.get("action", "")
        evidence["remediation_queries"] = remediation.get("queries", [])
        evidence["remediation_doc_count"] = len(remediation.get("docs") or [])

    state.last_evidence = dict(evidence)
    state.pending_docs = docs
    state.referenced_doc_ids.update(d.doc_id for d in docs)
    n_principle = len([d for d in docs if d.doc_type == "weekly"])
    n_experience = len([d for d in docs if d.doc_type == "daily"])
    GLOBAL_TRACKER.add_trace(
        stage="tool_result",
        label="retrieve_knowledge_tool 完成",
        content={"query": query[:80], "principle_count": n_principle,
                 "experience_count": n_experience,
                 "doc_ids": [d.doc_id for d in docs],
                 "evidence_status": evidence.get("status"),
                 "evidence_reason": evidence.get("reason"),
                 "top_score": evidence.get("top_score"),
                 "remediation_action": evidence.get("remediation_action", "")}
    )

    evidence_text = format_principle(docs) + "\n\n" + format_experience(docs)
    header = f"【知识检索证据】命中 {n_principle} 条心理原则、{n_experience} 条过往经历。\n"
    if remediation and remediation.get("action") in ("decompose", "expand"):
        if remediation["action"] == "decompose":
            fix_desc = f"分解为 {len(remediation.get('queries') or [])} 条子查询重检"
        else:
            fix_desc = "扩大召回名额重检"
        header += f"（首次证据不足，已自动{fix_desc}一次）\n"
    header += (
        "这是供你参考的中间证据，不要把本段原文直接发给用户；"
        "请消化后调用 psychological_consult_tool 产出最终回复。\n"
    )
    if state.retrieve_budget_left > 0:
        header += ("若证据与核心困扰明显无关，可换一个更聚焦核心困扰的查询再检索一次"
                   f"（本轮仅剩 {state.retrieve_budget_left} 次）；"
                   "若仍无相关证据，直接调用 psychological_consult_tool 做不依赖知识的自然回应。\n\n")
    else:
        header += ("本轮检索预算已用尽，不要再调用本工具；请直接调用 "
                   "psychological_consult_tool，基于现有证据与对话上下文自然回应。\n\n")
    return header + evidence_text


@tool(return_direct=True)
def psychological_consult_tool(user_input: str):
    """
    【心理咨询工具】处理用户情绪倾诉、内心迷茫，产出连贯心理对话回复。
    - 若本轮需要参考用户沉淀的心理原则/过往经历：先调 retrieve_knowledge_tool 检索，本工具会自动读取其证据；
    - 纯情绪承接、追问澄清、确认、寒暄等轮次无需检索，直接调用本工具即可自然回应。
    历史记忆、对话历史、检索证据均由工具内部从会话状态读取，无需传入。
    Args:
        user_input: 用户当前倾诉
    """
    memory_text = _format_memories_for_prompt(SESSION_STATE.similar_memories)
    chat_text = _format_chat_history(SESSION_STATE.full_chat_history)
    reasons_text = _format_guided_reasons(SESSION_STATE.guided_reasons)
    # 用户主动引用的资料（附上文档 / 追问某条回复）：优先级高于检索证据
    attached_text = format_attached_context(SESSION_STATE.attachments)
    has_attachments = bool(SESSION_STATE.attachments)
    # 消费本轮 retrieve_knowledge_tool 准备的证据（可能为空=本轮不检索，纯对话）；读后即清，防跨轮残留
    docs = SESSION_STATE.pending_docs
    SESSION_STATE.pending_docs = []
    GLOBAL_TRACKER.add_trace(
        stage="tool_call",
        label="调用工具: psychological_consult_tool",
        content={"user_input": user_input[:100],
                 "retrieved_knowledge": len(docs),
                 "attachments": len(SESSION_STATE.attachments),
                 "has_memories": bool(memory_text and memory_text != "暂无相关历史会话记录"),
                 "has_chat_history": bool(SESSION_STATE.full_chat_history)}
    )
    rag_agent = get_app_context().rag_agent()
    try:
        result = rag_agent.generate(
            user_input, docs,
            memory_context=memory_text, chat_history=chat_text, guided_reasons=reasons_text,
            attached_context=attached_text,
        )
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
                 "experience_count": result['raw']['experience_count'],
                 "from_attachment": has_attachments}
    )
    return f"【心理咨询回复】\n{result['answer']}"


def _format_doc_brief(idx: int, d: dict) -> str:
    """清单级输出：序号｜类型｜日期｜主题｜摘要首 60 字（不返回全文）"""
    date = _normalize_date(d.get("date")) or "无日期"
    topics = "、".join(d.get("topic") or []) or "无主题"
    summary = (d.get("summary") or d.get("content") or "").replace("\n", " ").strip()
    if len(summary) > 60:
        summary = summary[:60] + "…"
    return f"{idx}. [{d.get('doc_type')}] {date} · {topics} · {summary}\n"


@tool(return_direct=True)
def meta_filter_tool(
    doc_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    topic_keyword: Optional[str] = None,
    emotion: Optional[str] = None,
) -> str:
    """
    【模糊筛选工具】基于元数据 topic / 日期 / 情绪宽泛匹配文档，返回清单（不返回全文）
    使用场景：用户要某一类主题、某时间段、某种情绪的所有文章，不要求精确包含某段文字
    条件关系：不同条件取交集；同一字段多个值（多主题/多情绪）取并集
    Args:
        doc_type: daily / weekly / None 全部
        start_date: 起始日期 YYYY-MM-DD（可单独使用）
        end_date: 结束日期 YYYY-MM-DD（可单独使用）
        topic_keyword: 主题关键词，中文或英文标签均可（如"自我否定"/"Self_Understanding"）。主题类需求只用这一个参数
        emotion: 情绪英文标签如 Anxiety（多个用逗号分隔）
    """
    docs = meta_filter(
        doc_type=doc_type,
        start_date=start_date,
        end_date=end_date,
        topic_keyword=topic_keyword,
        keyword=None,
        emotion=emotion
    )
    # 主题标签解析不到 / 该主题下无文档时，按 keywords 字段兜底模糊匹配
    downgraded = False
    if not docs and topic_keyword:
        docs = meta_filter(
            doc_type=doc_type,
            start_date=start_date,
            end_date=end_date,
            topic_keyword=None,
            keyword=topic_keyword,
            emotion=emotion
        )
        downgraded = bool(docs)
    if not docs:
        return "未匹配到任何符合条件的文档"
    output = "【模糊筛选匹配结果】\n"
    output += f"共 {len(docs)} 篇（不同条件取交集，同一字段多值取并集）\n"
    if downgraded:
        output += "（注：主题标签未匹配到，已按关键词兜底匹配）\n"
    for idx, d in enumerate(docs, 1):
        output += _format_doc_brief(idx, d)
    output += "（需要某篇全文：告诉我序号；或到检索页「知识检索」查看完整列表）\n"
    return output


@tool(return_direct=True)
def precise_text_filter_tool(
    target_text: str,
    doc_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    topic_keyword: Optional[str] = None,
    emotion: Optional[str] = None,
) -> str:
    """
    【精准文本筛选工具】查找正文/摘要中精确包含 target_text 的文档，返回清单（不返回全文）
    使用场景：用户明确要求找出 "写到XX、包含XX文字" 的记录
    Args:
        target_text: 需要精确匹配的原文短句
        doc_type: daily / weekly
        start_date: 起始日期（可单独使用）
        end_date: 结束日期（可单独使用）
        topic_keyword: 前置缩小范围的主题关键词，中文或英文标签均可
        emotion: 情绪英文标签如 Anxiety
    """
    docs = precise_text_filter(
        target_text=target_text,
        doc_type=doc_type,
        start_date=start_date,
        end_date=end_date,
        topic_keyword=topic_keyword,
        keyword=None,
        emotion=emotion
    )
    # 主题标签解析不到 / 该主题下无文档时，按 keywords 字段兜底缩小范围
    downgraded = False
    if not docs and topic_keyword:
        docs = precise_text_filter(
            target_text=target_text,
            doc_type=doc_type,
            start_date=start_date,
            end_date=end_date,
            topic_keyword=None,
            keyword=topic_keyword,
            emotion=emotion
        )
        downgraded = bool(docs)
    if not docs:
        return f"没有文档精确包含文字：{target_text}"
    output = "【精准文本匹配结果】\n"
    output += f"（包含「{target_text}」）共 {len(docs)} 篇\n"
    if downgraded:
        output += "（注：主题标签未匹配到，已按关键词兜底缩小范围）\n"
    for idx, d in enumerate(docs, 1):
        output += _format_doc_brief(idx, d)
    output += "（需要某篇全文：告诉我序号；或到检索页「知识检索」查看完整列表）\n"
    return output


@tool(return_direct=True)
def summarize_memory_tool() -> str:
    """
    【会话总结工具】读取内存当前完整对话，生成记忆并后台持久化
    使用场景：用户明确要求"总结我们的对话""保存这次聊天""记住这次讨论"等
    无需传入参数，自动读取全局会话缓存
    """
    return summarize_memory()


@tool(return_direct=True)
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


@tool(return_direct=True)
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