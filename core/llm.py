import ollama
from openai import OpenAI
from typing import List, Dict, Generator

from config.model_config import SingleModel


class LLMError(Exception):
    """LLM 调用失败（超时/网络/上游错误），携带可读 message。"""

    def __init__(self, message: str, cause: Exception = None):
        super().__init__(message)
        self.cause = cause


class LLM:
    """统一 LLM 调用，根据 SingleModel.driver 自动选择 Ollama 或 OpenAI 兼容 API。"""

    def __init__(self, model: SingleModel, timeout: float = 320.0):
        self.model = model
        self.timeout = timeout
        if model.driver == "ollama":
            self._client = ollama.Client(timeout=timeout)
        elif model.driver == "api":
            self._client = OpenAI(
                api_key=model.api_key,
                base_url=model.base_url,
                timeout=timeout,
            )
        else:
            raise ValueError(f"不支持的 driver: {model.driver}")

    def _model_label(self) -> str:
        if self.model.driver == "ollama":
            return self.model.ollama_name
        return self.model.api_model_name

    def chat(self, messages: List[Dict], stream: bool = False, _retried: bool = False):
        # 统一异常兜底：非流式调用失败自动重试一次，仍失败则抛 LLMError（不裸抛上游异常）
        try:
            if self.model.driver == "ollama":
                return self._chat_ollama(messages, stream)
            else:
                return self._chat_api(messages, stream)
        except LLMError:
            raise
        except Exception as e:
            if not _retried:
                return self.chat(messages, stream=stream, _retried=True)
            raise LLMError(f"模型 {self._model_label()} 调用失败: {e}") from e

    def _chat_ollama(self, messages: List[Dict], stream: bool):
        if not stream:
            res = self._client.chat(
                model=self.model.ollama_name,
                messages=messages,
                options={"temperature": self.model.temperature}
            )
            return res["message"]["content"]
        else:
            stream_res = self._client.chat(
                model=self.model.ollama_name,
                messages=messages,
                stream=True,
                options={"temperature": self.model.temperature}
            )
            def gen():
                for chunk in stream_res:
                    cnt = chunk["message"]["content"]
                    if cnt:
                        yield cnt
            return gen()

    def _chat_api(self, messages: List[Dict], stream: bool):
        if not stream:
            res = self._client.chat.completions.create(
                model=self.model.api_model_name,
                messages=messages,
                temperature=self.model.temperature,
            )
            return res.choices[0].message.content
        else:
            stream_res = self._client.chat.completions.create(
                model=self.model.api_model_name,
                messages=messages,
                temperature=self.model.temperature,
                stream=True,
            )
            def gen():
                for chunk in stream_res:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content
            return gen()


