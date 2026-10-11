from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from api.common import catch_exception, CODE_OK, resp, CODE_PARAM_ERR
from config.model_config import OLLAMA_GLOBAL, GLOBAL_MODEL
from core.ollama_client import OLLAMA_CLIENT

router = APIRouter(prefix="/ollama", tags=["Ollama本地模型管理"])


def resolve_ollama_name(name: str) -> str:
    """支持 'small'/'large' 角色别名，其余视为原始 ollama 模型名。"""
    alias = {
        "small": GLOBAL_MODEL.small.ollama_name,
        "large": GLOBAL_MODEL.large.ollama_name,
    }
    return alias.get(name.strip().lower(), name.strip())

class ModelNameReq(BaseModel):
    model_name: str
    keep_alive: Optional[str] = None

class UpdateHostReq(BaseModel):
    host: str

# 获取当前Ollama远程服务地址
@router.get("/host")
@catch_exception
def get_ollama_host():
    return resp(CODE_OK, "获取远程Ollama地址成功", data={"host": OLLAMA_GLOBAL})

# 查询远程服务已下载全部模型
@router.get("/list")
@catch_exception
def list_remote_models():
    model_list = OLLAMA_CLIENT.list_local_models()
    return resp(CODE_OK, "远程Ollama本地模型列表", data={"models": model_list})

# 检查指定模型是否已下载
@router.post("/check")
@catch_exception
def check_model_exists(req: ModelNameReq):
    name = req.model_name.strip()
    exists = OLLAMA_CLIENT.is_model_exist(name)
    return resp(CODE_OK, "模型检查完成", data={"model_name": name, "exists": exists})

# 核心接口：远程一键下载+加载模型到显存（ollama ps可见）
@router.post("/start")
@catch_exception
def remote_load_model(req: ModelNameReq):
    model_name = resolve_ollama_name(req.model_name)
    if not model_name:
        return resp(CODE_PARAM_ERR, "模型名称不能为空")
    res_data = OLLAMA_CLIENT.full_start_model(model_name, keep_alive=req.keep_alive)
    return resp(CODE_OK, "模型加载完成", data=res_data)

# 查询当前运行中（已加载显存）模型，等价 ollama ps
@router.get("/ps")
@catch_exception
def list_running_models():
    models = OLLAMA_CLIENT.list_running_models()
    return resp(CODE_OK, "运行中模型列表", data={"models": models})