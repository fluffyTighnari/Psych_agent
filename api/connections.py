"""模型连接管理 API。

把「模型来源」抽象为 Connection（名称 + base_url + key + kind），
与既有 SingleModel 槽位解耦：
- UI 只需要管理「连接」和「每个槽位用哪个模型」；
- 运行时仍翻译成 SingleModel，不动 get_langchain_llm 与所有调用点。

**拉取模型列表必须由后端代理**：
浏览器直连 api.deepseek.com/models 会被 CORS 拦截，且 api_key 不应
出现在前端请求头里。这里用后端持有的 key 代发请求，只回传模型名。
"""
from typing import Optional

import requests
from fastapi import APIRouter
from pydantic import BaseModel

from api.common import catch_exception, CODE_OK, CODE_PARAM_ERR, CODE_SERVER_ERR, resp
from config.model_config import GLOBAL_MODEL, Connection, OLLAMA_GLOBAL

router = APIRouter(prefix="/connections", tags=["模型连接管理"])

# 拉取远端模型列表的超时（秒）
FETCH_TIMEOUT = 15


class ConnectionReq(BaseModel):
    id: str
    name: str
    kind: str                       # "ollama" | "openai"
    base_url: str = ""
    api_key: str = ""               # 传空字符串表示「保持原密钥不变」


class ConnectionDeleteReq(BaseModel):
    id: str


class ListModelsReq(BaseModel):
    """拉取模型列表：既支持已保存的连接，也支持「先填 URL 再试」。"""
    connection_id: Optional[str] = None
    kind: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None


def _normalize_base(base: str, kind: str) -> str:
    """规范化 base_url：补协议、去尾斜杠。"""
    b = (base or "").strip().rstrip("/")
    if not b:
        return b
    if not b.startswith("http://") and not b.startswith("https://"):
        b = "http://" + b
    # ollama 的原生 API 在根路径下（/api/tags），不要自动补 /v1
    return b


def _resolve_credentials(req: ListModelsReq) -> tuple[str, str, str]:
    """解析出 (kind, base_url, api_key)。已保存的连接优先用库里的值。"""
    if req.connection_id:
        conn = GLOBAL_MODEL.find_connection(req.connection_id)
        if conn is None:
            raise ValueError(f"连接不存在: {req.connection_id}")
        return conn.kind, _normalize_base(conn.base_url, conn.kind), conn.api_key

    kind = req.kind or "openai"
    base = _normalize_base(req.base_url or "", kind)
    key = req.api_key or ""
    return kind, base, key


@router.get("")
@catch_exception
def list_connections():
    """列出全部连接（api_key 脱敏）。"""
    return resp(
        CODE_OK,
        "获取连接列表成功",
        data={
            "connections": [c.to_dict(mask=True) for c in GLOBAL_MODEL.connections],
            "ollama_default": OLLAMA_GLOBAL,
        },
    )


@router.post("")
@catch_exception
def upsert_connection(req: ConnectionReq):
    """新增或更新连接。api_key 传空表示保持原值（支持脱敏值原样回传）。"""
    if not req.id.strip():
        return resp(CODE_PARAM_ERR, "连接 id 不能为空")

    existing = GLOBAL_MODEL.find_connection(req.id)
    # 传入脱敏值或空值 → 沿用原密钥，避免前端显示 *** 后保存把密钥抹掉
    incoming_key = req.api_key or ""
    if existing is not None and (not incoming_key or "*" in incoming_key):
        api_key = existing.api_key
    else:
        api_key = incoming_key

    conn = Connection(
        id=req.id.strip(),
        name=req.name.strip() or req.id.strip(),
        kind=req.kind,
        base_url=_normalize_base(req.base_url, req.kind),
        api_key=api_key,
    )
    GLOBAL_MODEL.upsert_connection(conn)
    GLOBAL_MODEL.save()

    return resp(
        CODE_OK,
        "连接已保存",
        data={"connections": [c.to_dict(mask=True) for c in GLOBAL_MODEL.connections]},
    )


@router.delete("")
@catch_exception
def delete_connection(req: ConnectionDeleteReq):
    """删除连接。至少保留一条，避免配置进入无连接可用的死状态。"""
    if len(GLOBAL_MODEL.connections) <= 1:
        return resp(CODE_PARAM_ERR, "至少保留一条连接")

    ok = GLOBAL_MODEL.remove_connection(req.id)
    if not ok:
        return resp(CODE_PARAM_ERR, f"连接不存在: {req.id}")

    GLOBAL_MODEL.save()
    return resp(CODE_OK, "连接已删除")


@router.post("/models")
@catch_exception
def list_models(req: ListModelsReq):
    """
    代理拉取可用模型列表。

    - kind=ollama  → GET {base}/api/tags
    - kind=openai  → GET {base}/models（OpenAI 兼容的 /v1/models）
    """
    try:
        kind, base, key = _resolve_credentials(req)
    except ValueError as e:
        return resp(CODE_PARAM_ERR, str(e))

    if not base:
        return resp(CODE_PARAM_ERR, "请先填写 base_url")

    try:
        if kind == "ollama":
            url = f"{base}/api/tags"
            r = requests.get(url, timeout=FETCH_TIMEOUT)
            r.raise_for_status()
            payload = r.json()
            names = [m.get("name", "") for m in payload.get("models", [])]
        else:
            url = f"{base}/models"
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            r = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            r.raise_for_status()
            payload = r.json()
            # OpenAI 兼容：{"data": [{"id": "..."}]}
            items = payload.get("data") if isinstance(payload, dict) else payload
            names = [m.get("id", "") for m in (items or []) if isinstance(m, dict)]
    except requests.exceptions.Timeout:
        return resp(CODE_SERVER_ERR, f"拉取模型列表超时（{FETCH_TIMEOUT}s），请检查地址是否可达")
    except requests.exceptions.RequestException as e:
        return resp(CODE_SERVER_ERR, f"拉取失败：{e}")
    except (ValueError, KeyError) as e:
        return resp(CODE_SERVER_ERR, f"响应解析失败：{e}")

    names = sorted(n for n in names if n)
    return resp(
        CODE_OK,
        f"拉取到 {len(names)} 个模型",
        data={"models": names, "kind": kind, "base_url": base},
    )
