import requests
from typing import List, Dict, Optional
from config.model_config import OLLAMA_GLOBAL

class OllamaRemoteClient:
    def __init__(self):
        self.base_url = OLLAMA_GLOBAL.rstrip("/")
        self.timeout = 120

    def list_local_models(self) -> List[str]:
        """获取Ollama服务已下载模型列表"""
        resp = requests.get(f"{self.base_url}/api/tags", timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("models", [])
        names = [m["name"] for m in models]
        return names

    def list_running_models(self) -> List[Dict]:
        """获取当前已加载到显存（运行中）的模型列表，原样透传 ollama ps 结果"""
        resp = requests.get(f"{self.base_url}/api/ps", timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("models", [])

    def is_model_exist(self, model_name: str) -> bool:
        """判断模型是否已拉取到服务本地"""
        local_models = self.list_local_models()
        return model_name in local_models

    def pull_model(self, model_name: str):
        """同步拉取模型，阻塞直到下载完成"""
        url = f"{self.base_url}/api/pull"
        payload = {"name": model_name, "stream": False}
        resp = requests.post(url, json=payload, timeout=300)
        resp.raise_for_status()
        return resp.json()

    def load_model_to_memory(self, model_name: str, keep_alive: Optional[str] = None):
        """空请求预热，将模型加载进显存，ollama ps可查询；keep_alive 控制常驻时长"""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model_name,
            "prompt": "",
            "stream": False,
            "num_predict": 1
        }
        if keep_alive:
            payload["keep_alive"] = keep_alive
        resp = requests.post(url, json=payload, timeout=180)
        resp.raise_for_status()
        return resp.json()

    def full_start_model(self, model_name: str, keep_alive: Optional[str] = None) -> Dict:
        """完整流程：不存在则pull下载 → 加载显存常驻（keep_alive 控制时长）"""
        result = {
            "model": model_name,
            "keep_alive": keep_alive,
            "pulled": False,
            "loaded": False,
            "msg": ""
        }
        if not self.is_model_exist(model_name):
            self.pull_model(model_name)
            result["pulled"] = True
        self.load_model_to_memory(model_name, keep_alive=keep_alive)
        result["loaded"] = True
        result["msg"] = f"模型 {model_name} 已加载至显存"
        return result

# 全局单例
OLLAMA_CLIENT = OllamaRemoteClient()
