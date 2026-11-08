# -*- coding: utf-8 -*-
"""知识文档检索原语：元数据模糊过滤 / 正文精准匹配。"""
from typing import Optional, List, Union
from dataclasses import asdict
from core.helper.knowledge_cache import KNOWLEDGE_CACHE
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.infra.context import get_app_context
from core.tools.primitives import has_any_filter, resolve_topics, to_list


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

    hit_ids = get_app_context().meta_db().filter_meta(
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

    hit_docs = meta_filter(
        doc_type=doc_type,
        start_date=start_date,
        end_date=end_date,
        topic_keyword=topic_keyword,
        keyword=keyword,
        emotion=emotion,
    )
    # meta_filter 返回的是 dict 列表（已 asdict），不是 doc_id 列表：直接用它做正文匹配
    target = str(target_text)
    match = [
        d for d in hit_docs
        if target in ((d.get("summary") or "") + (d.get("content") or ""))
    ]
    GLOBAL_TRACKER.add_trace(
        stage="tool_result",
        label="precise_text_filter 结果",
        content={"target_text": target, "hit_count": len(match),
                 "doc_ids": [d.get("doc_id") for d in match]}
    )
    return match