# -*- coding: utf-8 -*-
"""core.tools 包入口：对外 import 路径（from core.tools import X）。

组件访问已全部改为 ``core.infra.context.get_app_context()``；
模型/组件重建统一入口为 ``core.infra.context.rebuild_app()``。
"""
from core.tools.primitives import (
    has_any_filter, resolve_topics, to_list, generate_session_id,
    search_related_memories,
    _format_memories_for_prompt, _format_chat_history, _format_guided_reasons,
)
from core.tools.knowledge import meta_filter, precise_text_filter
from core.tools.memory_ops import (
    summarize_memory, search_memory, precise_memory_filter,
)
from core.tools.registry import (
    psychological_consult_tool, retrieve_knowledge_tool, meta_filter_tool,
    precise_text_filter_tool, summarize_memory_tool, search_memory_tool,
    precise_memory_filter_tool,
)

__all__ = [
    "has_any_filter", "resolve_topics", "to_list", "generate_session_id",
    "search_related_memories",
    "meta_filter", "precise_text_filter",
    "summarize_memory", "search_memory", "precise_memory_filter",
    "psychological_consult_tool", "retrieve_knowledge_tool", "meta_filter_tool",
    "precise_text_filter_tool",
    "summarize_memory_tool", "search_memory_tool", "precise_memory_filter_tool",
]
