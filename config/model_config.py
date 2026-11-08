import os
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

MODEL_DIR = BASE_DIR / "models"

EMBEDDING_MODEL = (
    MODEL_DIR /
    "embedding" /
    "bge-small-zh-v1.5"
)

RERANKING_MODEL = (
    MODEL_DIR /
    "reranking" /
    "models--BAAI--bge-reranker-base"
)

env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

# Ollama 服务地址（供 Connection 默认值与 ollama 客户端使用）
OLLAMA_GLOBAL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

# ===================== SingleModel dataclass =====================

@dataclass
class SingleModel:
    """通用模型包装，driver 强制为 ollama 或 api 之一。"""
    driver: str                          # "ollama" | "api"
    ollama_name: str = ""
    api_key: str = ""
    base_url: str = ""
    api_model_name: str = ""
    temperature: float = 0.0

    def __post_init__(self):
        if self.driver not in ("ollama", "api"):
            raise ValueError(f"driver 必须为 'ollama' 或 'api'，当前值: '{self.driver}'")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SingleModel":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ===================== Connection：统一连接配置 =====================

@dataclass
class Connection:
    """
    模型连接：把 ollama 与外部 API 对齐成同一形态。

    统一口径：名称 + base_url + api_key（ollama 可空）+ kind。
    kind 只在运行时决定用哪个 LangChain 客户端：
      - "ollama"   → ChatOllama（走原生 /api/chat）
      - "openai"   → ChatOpenAI（OpenAI 兼容协议）

    不把 ollama 强行改成 OpenAI 协议（它确实提供 /v1 兼容层），
    因为现有预处理/总结链路依赖 ChatOllama 的稳定性。
    统一的是**配置与交互形态**，不是底层协议。
    """
    id: str
    name: str
    kind: str                     # "ollama" | "openai"
    base_url: str = ""
    api_key: str = ""

    def __post_init__(self):
        if self.kind not in ("ollama", "openai"):
            raise ValueError(f"kind 必须为 'ollama' 或 'openai'，当前值: '{self.kind}'")

    def to_dict(self, mask: bool = False) -> dict:
        d = asdict(self)
        if mask:
            d["api_key"] = _mask_key(d.get("api_key", ""))
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Connection":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _mask_key(key: str) -> str:
    """脱敏：仅保留首尾各 4 位。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


def _default_connections() -> list[Connection]:
    """内置两条连接：本地 Ollama 与 DeepSeek（URL 从 .env 取）。"""
    ollama_url = os.getenv("OLLAMA_HOST", OLLAMA_GLOBAL)
    if not ollama_url.rstrip("/").endswith(":11434"):
        # OLLAMA_HOST 可能是 http://host:11434 或仅 host
        if not ollama_url.startswith("http"):
            ollama_url = f"http://{ollama_url}:11434"

    return [
        Connection(
            id="local-ollama",
            name="本地 Ollama",
            kind="ollama",
            base_url=ollama_url,
            api_key="",
        ),
        Connection(
            id="deepseek",
            name="DeepSeek",
            kind="openai",
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        ),
    ]


# ===================== 默认配置 =====================

def _default_small() -> SingleModel:
    return SingleModel(
        driver="ollama",
        ollama_name="qwen2:1.5b",
        temperature=0.0,
    )


def _default_large() -> SingleModel:
    return SingleModel(
        driver="ollama",
        ollama_name="qwen3.5:9b-128k",
        temperature=0.0,
    )


def _default_chat() -> SingleModel:
    return SingleModel(
        driver="api",
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url=os.getenv("DEEPSEEK_BASE_URL", ""),
        api_model_name="deepseek-flash",
        temperature=0.3,
    )


# ===================== GlobalModel 单例 =====================

class GlobalModel:
    """全局模型管理器，持久化到 config/model_store.json。"""

    __slots__ = ("small", "large", "chat", "connections")

    def __init__(
        self,
        small: SingleModel,
        large: SingleModel,
        chat: SingleModel,
        connections: Optional[list[Connection]] = None,
    ):
        self.small = small
        self.large = large
        self.chat = chat
        self.connections = connections if connections is not None else _default_connections()

    def save(self, path: Optional[Path] = None) -> None:
        p = path or MODEL_STORE_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            "small": self.small.to_dict(),
            "large": self.large.to_dict(),
            "chat": self.chat.to_dict(),
            # 连接也持久化，但同样不写密钥
            "connections": [
                {**c.to_dict(), "api_key": ""} for c in self.connections
            ],
        }
        # 不持久化密钥，运行时从 .env 注入
        for key in ("small", "large", "chat"):
            raw[key]["api_key"] = ""
        with open(p, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "GlobalModel":
        p = path or MODEL_STORE_PATH
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            conns = data.get("connections")
            gm = cls(
                small=SingleModel.from_dict(data["small"]),
                large=SingleModel.from_dict(data["large"]),
                chat=SingleModel.from_dict(data["chat"]),
                connections=[Connection.from_dict(c) for c in conns] if conns else None,
            )
        else:
            gm = cls(
                small=_default_small(),
                large=_default_large(),
                chat=_default_chat(),
            )
            gm.save(p)
        # 从环境变量注入密钥（JSON 中不持久化 api_key）
        gm._inject_env()
        return gm

    @staticmethod
    def _env_prefix_for(base_url: str) -> str:
        """根据 base_url 推断 .env 密钥前缀，支持多供应商（DEEPSEEK_* / QWEN_* / OPENAI_*）。"""
        if not base_url:
            return "DEEPSEEK"
        lower = base_url.lower()
        if "dashscope" in lower or "qwen" in lower:
            return "QWEN"
        if "openai" in lower:
            return "OPENAI"
        return "DEEPSEEK"

    def _inject_env(self) -> None:
        """用 .env 中的值填充空的 api_key / base_url（按供应商前缀，两者独立判断）。"""
        # 连接的密钥同样从 .env 补齐
        for conn in self.connections:
            if conn.kind != "openai":
                continue
            prefix = self._env_prefix_for(conn.base_url)
            if not conn.api_key:
                conn.api_key = os.getenv(f"{prefix}_API_KEY", "")
            if not conn.base_url:
                conn.base_url = os.getenv(f"{prefix}_BASE_URL", "")

        for slot_name in ("small", "large", "chat"):
            m = getattr(self, slot_name)
            if m.driver != "api":
                continue
            prefix = self._env_prefix_for(m.base_url)
            if not m.api_key:
                m.api_key = os.getenv(f"{prefix}_API_KEY", "")
            if not m.base_url:
                m.base_url = os.getenv(f"{prefix}_BASE_URL", "")


    # ===================== 连接 ↔ 槽位映射 =====================

    def find_connection(self, conn_id: str) -> Optional[Connection]:
        for c in self.connections:
            if c.id == conn_id:
                return c
        return None

    def upsert_connection(self, conn: Connection) -> None:
        """新增或更新连接（按 id 匹配）。"""
        for i, c in enumerate(self.connections):
            if c.id == conn.id:
                self.connections[i] = conn
                return
        self.connections.append(conn)

    def remove_connection(self, conn_id: str) -> bool:
        before = len(self.connections)
        self.connections = [c for c in self.connections if c.id != conn_id]
        return len(self.connections) < before

    def model_from_connection(
        self, conn_id: str, model_name: str, temperature: float = 0.0
    ) -> SingleModel:
        """把「连接 + 模型名」翻译成运行时 SingleModel（保持既有调用链不变）。"""
        conn = self.find_connection(conn_id)
        if conn is None:
            raise ValueError(f"连接不存在: {conn_id}")
        if conn.kind == "ollama":
            return SingleModel(
                driver="ollama", ollama_name=model_name, temperature=temperature
            )
        return SingleModel(
            driver="api",
            api_model_name=model_name,
            api_key=conn.api_key,
            base_url=conn.base_url,
            temperature=temperature,
        )


MODEL_STORE_PATH = BASE_DIR / "config" / "model_store.json"
GLOBAL_MODEL = GlobalModel.load(MODEL_STORE_PATH)


# ===================== LangChain 桥接 =====================

def get_langchain_llm(model: SingleModel):
    """
    根据 SingleModel 返回对应的 LangChain chat model 对象。
    - driver="api"  → ChatOpenAI（兼容 DeepSeek / Qwen API 等 OpenAI 式接口）
    - driver="ollama" → ChatOllama
    """
    if model.driver == "api":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model.api_model_name,
            api_key=model.api_key,
            base_url=model.base_url,
            temperature=model.temperature,
        )
    elif model.driver == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=model.ollama_name,
            temperature=model.temperature,
        )
    else:
        raise ValueError(f"不支持的 driver: {model.driver}")

