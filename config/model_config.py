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
        api_model_name="deepseek-v4-flash",
        temperature=0.3,
    )


# ===================== GlobalModel 单例 =====================

class GlobalModel:
    """全局模型管理器，持久化到 config/model_store.json。"""

    __slots__ = ("small", "large", "chat")

    def __init__(
        self,
        small: SingleModel,
        large: SingleModel,
        chat: SingleModel,
    ):
        self.small = small
        self.large = large
        self.chat = chat

    def save(self, path: Optional[Path] = None) -> None:
        p = path or MODEL_STORE_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            "small": self.small.to_dict(),
            "large": self.large.to_dict(),
            "chat": self.chat.to_dict(),
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
            gm = cls(
                small=SingleModel.from_dict(data["small"]),
                large=SingleModel.from_dict(data["large"]),
                chat=SingleModel.from_dict(data["chat"]),
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
        for slot_name in ("small", "large", "chat"):
            m = getattr(self, slot_name)
            if m.driver != "api":
                continue
            prefix = self._env_prefix_for(m.base_url)
            if not m.api_key:
                m.api_key = os.getenv(f"{prefix}_API_KEY", "")
            if not m.base_url:
                m.base_url = os.getenv(f"{prefix}_BASE_URL", "")


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


# ===================== 向后兼容导出 =====================

OLLAMA_GLOBAL = "http://127.0.0.1:11434"
