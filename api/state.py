from fastapi import APIRouter
from api.common import resp, CODE_OK, catch_exception, safe_serialize
from core.meta_db.context_meta import SESSION_STATE

router = APIRouter(prefix="/session", tags=["会话管理"])

@router.get("/state")
@catch_exception
def get_current_session_state():
    """获取当前完整会话状态（显式导出可序列化视图，避免 RLock 序列化崩溃）"""
    state_dict = SESSION_STATE.to_dict()
    return resp(CODE_OK, "获取会话状态成功", data=state_dict)

@router.post("/clear")
@catch_exception
def clear_current_session():
    """清空当前对话（保留session_id、记忆库不变）"""
    with SESSION_STATE.lock:
        SESSION_STATE.full_chat_history.clear()
        SESSION_STATE.similar_memories.clear()
        SESSION_STATE.referenced_doc_ids.clear()
        SESSION_STATE.guided_reasons.clear()
        SESSION_STATE.last_consult_query = ""
        SESSION_STATE.mode = ""
        SESSION_STATE.mode_problem = ""
        SESSION_STATE.mode_situation = ""
        SESSION_STATE.guided_ended = False
        SESSION_STATE.save_state()
    return resp(CODE_OK, "已清空本轮对话记录")

@router.post("/reset")
@catch_exception
def reset_all_session():
    """完全重置会话：清空对话、记忆引用、生成新session"""
    SESSION_STATE.clear_all()  # 你在SingleSessionState实现的清空db+内存方法
    return resp(CODE_OK, "会话已完全重置，开启新对话")