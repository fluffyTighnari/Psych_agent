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

也可以在**网页端改模型**：启动后打开 `http://127.0.0.1:8000` 的模型配置页，直接填 api_key / base_url，保存后立即生效。

> **API Key 不会持久化**：网页端填写的 key 只保存在当前后端进程内存中，`config/model_store.json` 里的 `api_key` 字段始终被清空；服务重启后会按 `base_url` 的供应商前缀从 `.env` 重新注入。需要长期使用，请把 key 写进 `.env`，不要只依赖网页端。

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

或在安装docker后运行：
```bash
docker compose up -d --build
```

## 模型配置说明

系统有三个模型槽位。网页端模型配置页可改，保存后立即生效；**非密钥字段**（`driver`、`ollama_name`、`api_model_name`、`base_url`、`temperature` 及连接结构）会持久化到 `config/model_store.json`，**`api_key` 不落盘**：

| 槽位 | 用途 | 默认 |
|---|---|---|
| `small` | 查询改写 / 预处理 | qwen2:1.5b 或 DeepSeek API |
| `large` | 会话总结 / RAG 生成 | qwen3.5:9b-128k 或 DeepSeek API |
| `chat` | 对话生成 / 引导推理 | DeepSeek API |

每个槽位 `driver=ollama` 时使用 `ollama_name`（本地 Ollama 模型名）；`driver=api` 时使用 `api_model_name` + `api_key` / `base_url`（云端 API）。`api_key` 在运行时从 `.env` 注入，不写入 JSON；修改 `base_url` 后，程序会按 `dashscope/qwen`、`openai`、其他（默认 DeepSeek）推断读取哪个 `*_API_KEY`。

| 数据 | 存储位置 | 是否持久化 | 是否加密 |
|---|---|---|---|
| `api_key` | 后端进程内存；启动时从 `.env` 注入 | 否（直接写 `.env` 才会长期保留） | 否 |
| `driver` / 模型名 / `base_url` / `temperature` | `config/model_store.json` | 是 | 否（明文 JSON） |
| 连接列表 | `config/model_store.json`，其中 `api_key` 字段为空 | 是 | 否 |

**结论：当前没有把 API Key 写入 SQLite 或加密数据库。** 网页端保存的 key 只是内存态；`GlobalModel.save()` 在写 `config/model_store.json` 前会强制把 `api_key` 置空。服务重启后，key 从 `.env` 读取；`.env` 为空则对应 API 调用会缺少 key。

## 引导型咨询评测

`guide_eval/` 是一套自包含的评测工具，用来量化「引导型咨询是否有效、哪家模型/哪版 prompt 更好、judge 本身准不准」：

- 12 条带人工标注矛盾的种子用例 × 5 种条件（无 prompt / 泛化咨询师 / 直接策略 / 生产引导 prompt / 极简引导）
- 多轮用户模拟器（隐藏背景 + 阻抗策略）+ 两阶段 LLM 判定器（证据编码 → 盲评）
- 核心链路指标：矛盾发现率 L1 → 针对性追问率 L2 → 用户自我解释率 L3 → 完整链路率
- judge 校准：人工盲评 + 二次加权 kappa / ICC(2,1)，不通过就不能下结论

```bash
python -m guide_eval.run --selftest      # 验证指标实现
python -m guide_eval.run --mock          # 离线跑通全流程（不需要 API key）
# 真实评测：cp guide_eval/models.example.json guide_eval/models.json 并填 .env
python -m guide_eval.run --models deepseek-chat,qwen-plus --limit-cases 8
```

不想逐家申请 key：`guide_eval/presets/` 提供三套现成配置——`openrouter.json`（一个 key 覆盖 GPT/Claude/Gemini/DeepSeek/Qwen/GLM/Kimi，推荐做主实验）、`opencode-go.json`（$10/月订阅，开源模型子集）、`cli.json`（`opencode run`/`claude -p`/`codex exec`，仅作生态效度补充）。

详见 [`guide_eval/README.md`](guide_eval/README.md)（方法论，含 §3.2b 单网关/订阅/CLI 选型）与 [`guide_eval/RATING_GUIDE.md`](guide_eval/RATING_GUIDE.md)（人工盲评标准）。

## 安全与隐私

- `.env`、`config/model_store.json`、`config/id_map.json` 均已被 `.gitignore` 排除，**不要**用 `git add -f` 强制加入
- **API Key 不在数据库里**：项目没有把 key 写入 SQLite，也没有加密数据库；`config/model_store.json` 是明文 JSON，且其中的 `api_key` 会被 `GlobalModel.save()` 强制清空
- 网页端填写的 key 只在本进程内存有效；服务/容器重启后从 `.env` 重新读取。长期配置请写 `.env`，并妥善保护该文件
- `data/`（个人日记）、`models/`（模型文件）、`store/`（运行数据）一律不入库
- 若 API Key 曾经泄露（例如误提交进 git 历史），请立即到对应平台**轮换密钥**

## 常见问题

- **页面显示"后端未连接"**：确认 8000 端口未被占用，查看 run.bat 终端日志中的报错
- **`model 'xxx' not found`**：Ollama 里没有该模型，执行 `ollama pull <模型名>`，或在网页模型配置里换成已安装的模型
- **检索不到内容**：先确认执行过 `python preprocess.py`，且 `data/notes/` 下有日记/复盘文件
- **改模型后不生效**：配置保存后会重置模型缓存，若仍未生效请重启服务

## Docker 部署（可选）

项目根已提供 `Dockerfile` / `docker-compose.yml` / `.dockerignore`，可一键起后端（复用宿主机 Ollama）：

```bash
# 前置：.env 已配置；本地模型已拉取到 ./models（见上文「拉取本地模型」）
#       config/model_store.json 若不存在，先创建空文件：copy NUL config\model_store.json
docker compose up -d --build
```

- 访问 `http://localhost:8000`
- 容器复用宿主机的 `./models`、`./data`、`./store` 挂载卷，无需重新下载模型/重新预处理
- 容器通过 `env_file: .env` 注入 API Key；网页端临时填写的 key 在容器重启后不会保留
- 容器通过 `host.docker.internal:11434` 访问宿主机 Ollama（compose 已设置 `OLLAMA_HOST=http://host.docker.internal:11434`），不是 compose 内置的 Ollama 服务
- 停止：`docker compose down`

> 注意：embedding/reranker 模型需先在本机 `./models/` 就绪再启动容器；qwen3.5:9b-128k 等对话模型由宿主机 Ollama 提供，需先在宿主机 `ollama pull`；首次调用会下载，耗时取决于网络。


![image](assets/brand\show.png)
