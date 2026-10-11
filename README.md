# PsychAgent

一个**本地优先的心理疏导 RAG 助手**：检索你自己的日记（Experience）与周复盘原则（Principle），结合历史会话记忆，用 LLM 生成个性化、有依据的疏导回复。

数据流：用户提问 → 意图路由 → 检索（向量 + BM25 + 重排序）→ 组装知识上下文（记忆 / 原则 / 经历）→ LLM 生成回复。

## 目录结构

| 目录 | 说明 | 是否入库 |
|---|---|---|
| `api/` | FastAPI 路由（聊天、模型配置、记忆、知识库、追踪） | 是 |
| `core/` | 核心业务（agent 路由、RAG、检索、缓存、预处理、总结） | 是 |
| `config/` | 模型 / 路径 / prompt / 主题配置 | 是（不含 model_store.json、id_map.json） |
| `web/` | 前端静态页面（index.html / app.js / style.css） | 是 |
| `docs/` | 架构诊断与稳定性计划 | 是 |
| `data/` | 个人数据：`data/notes/` 原始日记、`data/knowledge/` 预处理结果 | **否**（隐私） |
| `models/` | 本地模型（embedding / reranker，HuggingFace 拉取） | **否**（体积 GB 级） |
| `store/` | 运行态数据（SQLite、向量库、BM25 索引） | **否** |
| `.env` | API 密钥（从 `.env.example` 复制） | **否** |

## 快速开始

### 1. 环境要求

- Python 3.10+（开发环境 3.13）
- [Ollama](https://ollama.com)（本地对话模型）
- 能访问 HuggingFace（拉取 embedding / reranker 模型）

### 2. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 配置 API Key（必读）

```bash
copy .env.example .env
```

打开 `.env` 填写。需要填哪些取决于你用哪家模型：

- **DeepSeek（默认）**：到 [platform.deepseek.com](https://platform.deepseek.com) → API Keys → 创建密钥，填 `DEEPSEEK_API_KEY`；`DEEPSEEK_BASE_URL` 保持 `https://api.deepseek.com`
- **通义千问 DashScope（可选）**：到 [dashscope.console.aliyun.com/apiKey](https://dashscope.console.aliyun.com/apiKey) 创建，填 `QWEN_API_KEY` 与 `QWEN_BASE_URL`（`https://dashscope.aliyuncs.com/v1`）
- **HuggingFace Token（可选）**：拉取受限模型时需要，到 [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) 创建，填 `HF_TOKEN`

也可以在**网页端改模型**：启动后打开 `http://127.0.0.1:8000` 的模型配置页，直接填 api_key / base_url，保存后立即生效（写入 `config/model_store.json`，该文件已 gitignore，不会入库）。

### 4. 拉取本地模型

**a) 向量模型（检索必需）**

```bash
huggingface-cli download BAAI/bge-small-zh-v1.5 --local-dir models/embedding/bge-small-zh-v1.5
```

**b) 重排序模型（检索精排）**

```bash
huggingface-cli download BAAI/bge-reranker-base --local-dir models/reranking/models--BAAI--bge-reranker-base
```

**c) Ollama 对话模型（预处理 / 会话总结用）**

```bash
ollama pull qwen3.5:9b-128k   # 大模型
ollama pull qwen2:1.5b        # 小模型
```

一键启动 Ollama 模型：双击 `start_models.bat`，或运行 `python large_model_run.py` / `python small_model_run.py`。

### 5. 准备个人数据并预处理

- 日常日记：放入 `data/notes/Daily_thoughts/`，文件名如 `2026.10.11.md`
- 周复盘：放入 `data/notes/Weekly_thoughts/`，格式为 `### 标题` + `#### problem / #### analysis / #### solution` 三段
- 运行预处理（增量：只处理变更的源文件，结果写入 `data/knowledge/`）：

```bash
python preprocess.py
```

### 6. 启动服务

```bash
python main.py
```

或双击 `run.bat`（自动探测 Python 解释器、等待后端就绪后打开网页 `http://127.0.0.1:8000`）。

## 模型配置说明

系统有三个模型槽位（网页端模型配置页可改，保存即生效并持久化到 `config/model_store.json`）：

| 槽位 | 用途 | 默认 |
|---|---|---|
| `small` | 查询改写 / 预处理 | qwen2:1.5b 或 DeepSeek API |
| `large` | 会话总结 / RAG 生成 | qwen3.5:9b-128k 或 DeepSeek API |
| `chat` | 对话生成 / 引导推理 | DeepSeek API |

每个槽位 `driver=ollama` 时使用 `ollama_name`（本地 Ollama 模型名）；`driver=api` 时使用 `api_model_name` + `api_key` / `base_url`（云端 API）。

## 安全与隐私

- `.env`、`config/model_store.json`、`config/id_map.json` 均已被 `.gitignore` 排除，**不要**用 `git add -f` 强制加入
- `data/`（个人日记）、`models/`（模型文件）、`store/`（运行数据）一律不入库
- 若 API Key 曾经泄露（例如误提交进 git 历史），请立即到对应平台**轮换密钥**

## 常见问题

- **页面显示"后端未连接"**：确认 8000 端口未被占用，查看 run.bat 终端日志中的报错
- **`model 'xxx' not found`**：Ollama 里没有该模型，执行 `ollama pull <模型名>`，或在网页模型配置里换成已安装的模型
- **检索不到内容**：先确认执行过 `python preprocess.py`，且 `data/notes/` 下有日记/复盘文件
- **改模型后不生效**：配置保存后会重置模型缓存，若仍未生效请重启服务