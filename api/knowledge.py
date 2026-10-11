from fastapi import APIRouter
from api.common import resp, CODE_OK, catch_exception, safe_serialize
from core.helper.knowledge_cache import KNOWLEDGE_CACHE

router = APIRouter(prefix="/knowledge", tags=["知识库查询"])

@router.get("/all")
@catch_exception
def get_all_knowledge_docs():
    """加载全部知识库文档，用于前端侧边全局展示"""
    serialized = [safe_serialize(d) for d in KNOWLEDGE_CACHE.documents]
    return resp(CODE_OK, "加载全部知识库成功", data=serialized)