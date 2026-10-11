import os
import re
from datetime import datetime
from dataclasses import asdict
from typing import Optional, List, Union

from fastapi import APIRouter
from api.common import resp, CODE_OK, CODE_SERVER_ERR, catch_exception
from config.model_config import GLOBAL_MODEL, SingleModel
from config.path_config import DATA_DIR, NOTES_DIR
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.tools import precise_text_filter, meta_filter, precise_memory_filter, search_memory, summarize_memory

def normalize_opt_str(s: Optional[str]) -> Optional[str]:
    """空字符串/全空格 → None；其余返回strip之后的值"""
    if s is None:
        return None
    s_strip = s.strip()
    return s_strip if s_strip else None

# 非法文件名字符：Windows 保留字符 + 控制字符；分隔符一律剔除，防路径穿越
_FILENAME_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

def _sanitize_filename(name: str, default: str) -> str:
    """清洗保存文件名：去掉路径部分、剔除非法字符、限定长度，返回带 .md 的安全文件名。"""
    base = name.strip().replace("\\", "/")
    base = os.path.basename(base)          # 只保留文件名部分，剔除路径（防 ../x 穿越）
    base = _FILENAME_BAD_CHARS.sub("_", base)
    base = base.strip().strip(".")
    if not base:
        base = default
    if not base.endswith(".md"):
        base += ".md"
    return base[:80]

router = APIRouter(prefix="/tool", tags=["快捷工具"])


@router.post("/summarize")
@catch_exception
def trigger_session_summary():
    """一键总结当前会话，后台持久化记忆"""
    tool_result = summarize_memory()
    if "【会话总结失败】" in tool_result:
        return resp(CODE_SERVER_ERR, "会话总结工具执行失败", extra={"result": tool_result})
    return resp(CODE_OK, "会话总结完成", data={"summary_text": tool_result})


# 1 获取当前全部模型配置，前端渲染编辑表单
def _mask_api_key(key: str) -> str:
    """脱敏 api_key，仅保留首尾各 4 位。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


def _is_masked_or_empty(key: str) -> bool:
    return (not key) or ("*" in key)


def _public_model(m) -> dict:
    d = asdict(m)
    d["api_key"] = _mask_api_key(d.get("api_key", ""))
    return d


@router.get("/model")
@catch_exception
def get_all_model_config():
    data = {
        "small": _public_model(GLOBAL_MODEL.small),
        "large": _public_model(GLOBAL_MODEL.large),
        "chat": _public_model(GLOBAL_MODEL.chat)
    }
    return resp(CODE_OK, "获取模型配置成功", data=data)

# 2 前端提交修改，更新全局内存并持久化文件
# 字段与 SingleModel 严格对齐，保证 SingleModel(**model_dump()) 可无损构造
from pydantic import BaseModel
class ModelConfigItem(BaseModel):
    driver: str
    ollama_name: str = ""
    api_key: str = ""
    base_url: str = ""
    api_model_name: str = ""
    temperature: float = 0.0

class ModelConfigReq(BaseModel):
    small: ModelConfigItem
    large: ModelConfigItem
    chat: ModelConfigItem

@router.post("/model/update")
@catch_exception
def update_model_config(req: ModelConfigReq):
    # 覆盖全局内存配置；api_key 已脱敏返回，未修改时保留原值避免覆盖
    for slot, item in (("small", req.small), ("large", req.large), ("chat", req.chat)):
        d = item.model_dump()
        if _is_masked_or_empty(d.get("api_key", "")):
            d["api_key"] = getattr(GLOBAL_MODEL, slot).api_key
        setattr(GLOBAL_MODEL, slot, SingleModel(**d))
    # 给 driver=api 但 api_key/base_url 为空的槽位注入 .env 配置（如从 ollama 切到 api）
    GLOBAL_MODEL._inject_env()
    # 写入json持久化，重启服务不丢失
    GLOBAL_MODEL.save()
    # 重置各模块缓存的 LLM / Agent 实例，使新配置立即生效（无需重启）
    from core.agent import reset_llm_cache as reset_agent_llm_cache
    from core.tools import reset_llm_cache as reset_tools_llm_cache
    reset_agent_llm_cache()
    reset_tools_llm_cache()
    return resp(CODE_OK, "模型配置已更新并保存，立即生效")

# ===================== 入参模型 =====================
class MetaFilterReq(BaseModel):
    doc_type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    topic_keyword: Optional[Union[str, List[str]]] = None
    keyword: Optional[Union[str, List[str]]] = None
    emotion: Optional[Union[str, List[str]]] = None

class TextFilterReq(BaseModel):
    target_text: str
    doc_type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    topic_keyword: Optional[Union[str, List[str]]] = None
    keyword: Optional[Union[str, List[str]]] = None
    emotion: Optional[Union[str, List[str]]] = None

class MemoryPreciseFilterReq(BaseModel):
    topic_keyword: Optional[Union[str, List[str]]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    keyword: Optional[Union[str, List[str]]] = None
    emotion: Optional[Union[str, List[str]]] = None

class MemoryVectorSearchReq(BaseModel):
    query: str
    top_k: int = 3

# ===================== 接口 =====================
@router.post("/search/meta-filter")
@catch_exception
def api_meta_filter(req: MetaFilterReq):
    """通用元数据过滤（返回结构化文档列表）"""
    res = meta_filter(
        doc_type=normalize_opt_str(req.doc_type),
        start_date=normalize_opt_str(req.start_date),
        end_date=normalize_opt_str(req.end_date),
        topic_keyword=req.topic_keyword,
        keyword=req.keyword,
        emotion=req.emotion
    )
    return resp(CODE_OK, "元数据检索完成", data={"result": res})

@router.post("/search/text-filter")
@catch_exception
def api_text_filter(req: TextFilterReq):
    """知识库文档精准全文检索+元过滤（返回结构化文档列表）"""
    res = precise_text_filter(
        target_text=req.target_text,
        doc_type=normalize_opt_str(req.doc_type),
        start_date=normalize_opt_str(req.start_date),
        end_date=normalize_opt_str(req.end_date),
        topic_keyword=req.topic_keyword,
        keyword=req.keyword,
        emotion=req.emotion
    )
    return resp(CODE_OK, "文档精准检索完成", data={"result": res})

@router.post("/search/memory-filter")
@catch_exception
def api_memory_precise_filter(req: MemoryPreciseFilterReq):
    """历史记忆精准元数据过滤（返回结构化记忆列表）"""
    res = precise_memory_filter(
        topic_keyword=req.topic_keyword,
        start_date=normalize_opt_str(req.start_date),
        end_date=normalize_opt_str(req.end_date),
        keyword=req.keyword,
        emotion=req.emotion
    )
    return resp(CODE_OK, "记忆条件检索完成", data={"result": res})

@router.post("/search/memory-vector")
@catch_exception
def api_memory_vector_search(req: MemoryVectorSearchReq):
    """记忆向量语义检索（仅自然query）"""
    res = search_memory(query=req.query, top_k=req.top_k)
    return resp(CODE_OK, "记忆语义检索完成", data={"result": res})

@router.post("/preprocess")
@catch_exception
def api_preprocess():
    """preprocess过程：
    preprocessor统一预处理目录下所有文档，生成json文件
    document_loader装载所有json文件
    embedding_model构建所有知识向量
    VectorDB更新知识库
    BM25更新索引库"""
    from config.model_config import GLOBAL_MODEL, EMBEDDING_MODEL
    from config.path_config import KNOWLEDGE_DIR, DATA_DIR, VECTOR_DB_DIR, COLLECTION_NAME, BM25_PATH, META_DB_PATH
    from core.helper.BM25 import BM25TagIndexer
    from core.loader.document_loader import DocumentLoader
    from core.embedding.embedding import EmbeddingModel
    from core.meta_db.knowledge_meta import KnowledgeMetaDB
    from core.vector_db.documents_vector_db import VectorDB
    from core.llm import LLM
    from core.helper.preprocessor import DocumentPreprocessor

    model = LLM(
        GLOBAL_MODEL.large,
    )

    preprocessor = DocumentPreprocessor(
        model,
        KNOWLEDGE_DIR
    )

    preprocessor.preprocess(
        DATA_DIR
    )

    loader = DocumentLoader()
    all_docs = loader.load_documents()
    loader.create_id_map()

    knowledge_db = KnowledgeMetaDB(
        META_DB_PATH
    )
    knowledge_db.batch_upsert(all_docs)

    embedding_model = EmbeddingModel(EMBEDDING_MODEL)

    embeddings = embedding_model.encode_documents(all_docs)

    vector_db = VectorDB(
        VECTOR_DB_DIR,
        COLLECTION_NAME
    )

    vector_db.sync_all_documents(all_docs, embeddings)

    indexer = BM25TagIndexer(
        documents=all_docs,
        bm25_path=BM25_PATH,
        topic_weight=3,
        keyword_weight=1
    )

    # 写入即生效：刷新内存知识缓存，网页检索/知识库列表无需重启即可看到新数据
    from core.helper.knowledge_cache import KNOWLEDGE_CACHE
    KNOWLEDGE_CACHE.reload()

    GLOBAL_TRACKER.add_trace(
        stage="preprocess",
        label="预处理阶段已完成",
        content={"knowledge_docs": len(KNOWLEDGE_CACHE.documents)}
    )

class SaveDailyReq(BaseModel):
    """保存日常短文"""
    content: str
    custom_filename: Optional[str]

class SaveWeeklyReq(BaseModel):
    """保存周心理复盘（三段固定格式）"""
    filename: str
    title: str
    problem: str
    analysis: str
    solution: str

DAILY_DIR = NOTES_DIR / "Daily_thoughts"
WEEKLY_DIR = NOTES_DIR / "Weekly_thoughts"
# ===================== 接口1：保存Daily日常短文 =====================
@router.post("/article/save-daily")
@catch_exception
def save_daily_article(req: SaveDailyReq):
    if req.custom_filename and req.custom_filename.strip():
        file_name = _sanitize_filename(req.custom_filename, "untitled")
    else:
        now = datetime.now()
        file_name = f"{now.year}.{now.month}.{now.day}.md"

    file_path = DAILY_DIR / file_name
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    # 写入md纯内容
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(req.content.strip())

    return resp(
        CODE_OK,
        "日常文章持久化成功",
        data={
            "save_path": str(file_path),
            "file_name": file_name,
            "type": "daily"
        }
    )

@router.post("/article/save-weekly")
@catch_exception
def save_weekly_article(req: SaveWeeklyReq):
    md_content = f"""### {req.title}
#### problem
{req.problem.strip()}

#### analysis
{req.analysis.strip()}

#### solution
{req.solution.strip()}
"""
    # 处理文件名（清洗：剔路径、剔非法字符、限长，防路径穿越）
    file_name = _sanitize_filename(req.filename, "weekly_untitled")
    file_path = WEEKLY_DIR / file_name
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)

    # 写入文件
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return resp(
        CODE_OK,
        "周复盘文章持久化成功",
        data={
            "save_path": str(file_path),
            "file_name": file_name,
            "type": "weekly",
            "title": req.title
        }
    )