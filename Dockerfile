# ============================================================
# PsychAgent 后端镜像（Python FastAPI + 本地 RAG）
# 构建：docker compose build   或   docker build -t psych-agent .
# ============================================================
FROM python:3.12-slim

# 统一 UTF-8，避免中文输出/文件编码问题；OLLAMA_HOST 默认本机，可由 compose 覆盖
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OLLAMA_HOST=http://127.0.0.1:11434

# 运行时系统库：onnxruntime（chromadb 依赖）在 slim 镜像上需要 libgomp1
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# 先装依赖，利用 Docker 构建缓存（requirements.txt 已锁定版本）
# 说明：清华源会对 pip 流量返回 403（非常用软件特征），且 pypi.org 在国内常超时；
#       这里只用单一镜像源，不配 --extra-index-url，避免 pip 为每个包去连不可达的 PyPI。
#       如需换源，构建时覆盖：docker compose build --build-arg PIP_INDEX_URL=...
ARG PIP_INDEX_URL=https://repo.huaweicloud.com/repository/pypi/simple

# 默认装 CPU 版 torch：PyPI 的 Linux wheel 默认带 CUDA，会额外拉 nvidia-* 约 4~5GB，
# Docker Desktop 无 GPU 时纯属浪费。需要 GPU 时用 --build-arg INSTALL_CPU_TORCH=0。
ARG INSTALL_CPU_TORCH=1
ARG TORCH_VERSION=2.15.0
RUN if [ "$INSTALL_CPU_TORCH" = "1" ]; then \
        pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==${TORCH_VERSION}; \
    fi

RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} --timeout 120 --retries 5 -r requirements.txt

# 拷贝业务代码；data/models/store/.env 由 .dockerignore 排除，运行时以卷挂载
COPY . .

EXPOSE 8000

# 健康检查：探活根路由
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3)" || exit 1

# 默认不启用 reload（RELOAD=1 为开发调试用）
CMD ["python", "main.py"]