from fastapi import APIRouter
from api.common import resp, CODE_OK, catch_exception, safe_serialize
from core.helper.memory_cache import MEMORY_CACHE

router = APIRouter(prefix="/memory", tags=["历史记忆查询"])

@router.get("/all")
@catch_exception
def get_all_history_memory():
    """加载所有持久化历史会话记忆，前端全局面板渲染"""
    serialized = [safe_serialize(m) for m in MEMORY_CACHE.memories]
    return resp(CODE_OK, "加载全部历史记忆成功", data=serialized)