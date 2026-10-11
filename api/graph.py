from fastapi import APIRouter
from api.common import resp, CODE_OK, catch_exception
from core.meta_db.context_meta import SESSION_STATE
from core.helper.knowledge_cache import KNOWLEDGE_CACHE
from core.helper.memory_cache import MEMORY_CACHE
from typing import List, Dict

router = APIRouter(prefix="/graph", tags=["会话关联图谱渲染接口"])

# 节点类型常量，前端区分样式/颜色
TYPE_SESSION = "session"
TYPE_MEMORY = "memory"
TYPE_DOC = "document"
TYPE_REASON = "reason"

# 连线关系常量
REL_SESSION_BIND_MEMORY = "session_bind_memory"
REL_SESSION_REF_DOC = "session_ref_doc"
REL_MEMORY_REF_DOC = "memory_ref_doc"
REL_MEMORY_RELATED = "memory_related_memory"
REL_REASON_NEXT = "reason_next"
REL_SESSION_REASON = "session_bind_reason"

@router.get("/session-relation")
@catch_exception
def get_session_relation_graph():
    """
    获取当前会话完整关联图谱：
    会话节点 + 相似记忆节点（+ related_memory 2层展开）+ 关联文档节点 + 引导推理链节点
    """
    nodes: List[Dict] = []
    links: List[Dict] = []
    state = SESSION_STATE

    # 1. 构造根会话节点
    session_id = state.session_id
    nodes.append({
        "id": session_id,
        "name": "当前会话",
        "type": TYPE_SESSION,
        "summary": state.last_consult_query
    })

    # 2. 相似记忆（level 0）+ 其引用文档
    all_doc_ids = set(state.referenced_doc_ids)
    memory_node_ids = [mem.id for mem in state.similar_memories]
    for mem in state.similar_memories:
        nodes.append({
            "id": mem.id,
            "name": mem.title,
            "type": TYPE_MEMORY,
            "summary": (mem.summary or "")[:120]
        })
        mem_doc_ids = set(mem.referenced_documents or [])
        all_doc_ids.update(mem_doc_ids)
        for d_id in mem_doc_ids:
            links.append({"source": mem.id, "target": d_id, "relation": REL_MEMORY_REF_DOC})

    # 3. related_memory 2 层展开（仅新增记忆结点，不拉取它们的文档，控制结点规模）
    seen = set(memory_node_ids)
    frontier = list(memory_node_ids)
    for _ in range(2):
        next_frontier = []
        for mid in frontier:
            mem = MEMORY_CACHE.cache.get(mid)
            if not mem:
                continue
            for rel_id in (mem.related_memory or []):
                if rel_id in seen:
                    continue
                seen.add(rel_id)
                next_frontier.append(rel_id)
                links.append({"source": mid, "target": rel_id, "relation": REL_MEMORY_RELATED})
        frontier = next_frontier

    related_ids = seen - set(memory_node_ids)
    for mid in related_ids:
        mem = MEMORY_CACHE.cache.get(mid)
        if not mem:
            continue
        nodes.append({
            "id": mem.id,
            "name": mem.title,
            "type": TYPE_MEMORY,
            "summary": (mem.summary or "")[:120]
        })

    # 4. 文档节点
    for doc in KNOWLEDGE_CACHE.get_by_ids(all_doc_ids):
        if not doc:
            continue
        nodes.append({
            "id": doc.doc_id,
            "name": doc.title,
            "source": doc.source,
            "type": TYPE_DOC,
            "summary": doc.summary
        })

    # 5. 会话 → 相似记忆 连线
    for mem_node_id in memory_node_ids:
        links.append({"source": session_id, "target": mem_node_id, "relation": REL_SESSION_BIND_MEMORY})

    # 6. 会话 → 顶层引用文档 连线
    for d_id in state.referenced_doc_ids:
        links.append({"source": session_id, "target": d_id, "relation": REL_SESSION_REF_DOC})

    # 7. guided_reasons 结点（问答对 + 递进链）
    reasons = state.guided_reasons
    reason_node_ids = []
    pair_count = len(reasons) // 2
    for i in range(pair_count):
        q = reasons[2 * i].get("content", "")
        a = reasons[2 * i + 1].get("content", "")
        nid = f"reason_{i}"
        reason_node_ids.append(nid)
        nodes.append({
            "id": nid,
            "name": (q or "")[:40] or f"引导问题{i + 1}",
            "type": TYPE_REASON,
            "summary": f"Q: {q}\nA: {a}"
        })
    # 末尾未成对的引导问题 → 待回答结点
    if len(reasons) % 2 == 1:
        q = reasons[-1].get("content", "")
        nid = f"reason_{pair_count}"
        reason_node_ids.append(nid)
        nodes.append({
            "id": nid,
            "name": (q or "")[:40] or f"引导问题{pair_count + 1}",
            "type": TYPE_REASON,
            "summary": f"Q: {q}\nA: （待回答）"
        })

    # 递进链
    for i in range(len(reason_node_ids) - 1):
        links.append({"source": reason_node_ids[i], "target": reason_node_ids[i + 1], "relation": REL_REASON_NEXT})
    if reason_node_ids:
        links.append({"source": session_id, "target": reason_node_ids[0], "relation": REL_SESSION_REASON})

    return resp(
        CODE_OK,
        "会话关联图谱数据生成成功",
        data={
            "nodes": nodes,
            "links": links
        }
    )