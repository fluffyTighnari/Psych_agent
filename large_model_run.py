import subprocess

from config.model_config import GLOBAL_MODEL

# 动态读取当前大模型配置（ollama 名称），配置更新后无需改脚本
model_name = GLOBAL_MODEL.large.ollama_name or "qwen3.5:9b-128k"
print(f"启动模型：{model_name}")
subprocess.run(["ollama", "run", model_name])
