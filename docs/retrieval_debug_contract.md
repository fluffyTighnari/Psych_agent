# 检索优化调试系统 · 接口契约（冻结版 v1）

> 本文件是所有并行实现必须严格遵守的接口契约。任何一方需要偏离，必须先通知 Lead 更新本文件。
> 目标：`web/index.html` + `web/app.js` 新增「检索调试」视图，通过 `api/retrieval_debug.py` 暴露的接口，
> 让使用者勾选 dense / bm25 / rrf / rerank 的任意组合，输入 prompt，查看每一阶段结果与结构化日志。

## 0. 交付物与写入范围（互不重叠）

| 交付物 | 负责人 | 写入范围 |
|---|---|---|
| 检索流水线 `core/helper/retrieval_pipeline.py`（新文件） | pipeline-dev | `core/helper/retrieval_pipeline.py` |
| 调试 API `api/retrieval_debug.py`（新文件）+ 挂载 `main.py` | api-dev | `api/retrieval_debug.py`、`main.py` |
| 前端视图 `web/index.html`、`web/app.js`、`web/style.css` | web-dev | 上述 3 个文件 |
| 端到端验证脚本 + 验证报告 | verifier | `scripts/verify_retrieval_debug.py` |

**禁止**修改 `core/helper/retriever.py`（生产链路 `Retriever.retrieve` 必须保持行为不变，它仍被 `core/helper/RAG_agent.py` 使用）。

## 1. 运行时依赖的现成组件（只读，不要改）

```python
from config.model_config import EMBEDDING_MODEL, RERANKING_MODEL   # 本地 SentenceTransformer 路径
from config.path_config import (VECTOR_DB_DIR, COLLECTION_NAME, BM25_PATH,
                                META_DB_PATH, KNOWLEDGE_DIR)
from core.embedding.embedding import EmbeddingModel                # .encode(text) -> np.ndarray(512,)
from core.vector_db.documents_vector_db import VectorDB             # .query(emb, top_k) -> chroma结果
from core.helper.BM25 import BM25TagIndexer                        # BM25TagIndexer(documents=[], bm25_path=BM25_PATH)
from core.helper.reranker import Reranker                          # Reranker(RERANKING_MODEL, score_threshold=0.08)
from core.helper.prompt_optimizer import PromptOptimizer           # .optimize_prompt(prompt) -> {"search_query","match_topics","keywords"}
from core.llm import LLM                                           # LLM(GLOBAL_MODEL.small)
from core.loader.knowledge_loader import KnowledgeLoader           # .load_knowledge(ids) -> list[Document]（顺序保持）
from core.helper.knowledge_cache import KNOWLEDGE_CACHE            # .documents / .cache / .reload()
from core.helper.trace_tracker import TraceTracker, GLOBAL_TRACKER
from core.schema import Document
```

- 生产链路里 `Retriever` 的 Query 优化、dense、BM25、RRF 细节见 `core/helper/retriever.py`，**本模块要复用同样的算法**（RRF k=60、BM25 token = jieba(raw_query)+match_topics+keywords、dense 检索文本 = `search_query + raw_query`）。
- 本地 BM25 索引文件：`store/bm25_store/bm25`；向量库 collection：`psych_notes`（当前 11 篇文档）。
- 模型加载较重（embedding 约 1s、reranker 约 4s），**必须 lazy + 进程内复用**，不要在 import 期加载，也不要在 `main.py` 启动时加载。

## 2. `core/helper/retrieval_pipeline.py` 契约

### 2.1 组件缓存（进程级单例，懒加载，线程安全）

```python
def get_retrieval_components() -> dict:
    """返回 {'embedding_model','vector_db','bm25','prompt_optimizer','knowledge_loader','reranker'}
       首次调用装载本地模型；后续调用直接复用。失败时抛异常（由 API 层兜底）。"""
```

### 2.2 流水线

```python
class RetrievalPipeline:
    def __init__(self, embedding_model, vector_db, bm25, prompt_optimizer,
                 knowledge_loader, reranker): ...
    def run(self, query: str, *, dense: bool = True, bm25: bool = True, rrf: bool = True,
            rerank: bool = True, raw_top_k: int = 6, final_top_k: int = 3,
            rrf_k: int = 60, score_threshold: float | None = None,
            trace: TraceTracker | None = None) -> dict: ...
```

`run()` 返回**纯 Python 可 JSON 序列化**的 dict（内部不得出现 numpy 标量/ndarray，分数统一 `round(float(x), 6)`）：

```python
{
  "stages": [  # 只包含本次启用的阶段，顺序固定：optimize_prompt, dense, bm25, rrf, rerank
    {
      "name": "dense",                     # optimize_prompt | dense | bm25 | rrf | rerank
      "label": "向量召回",                  # 中文短标签
      "enabled": True,
      "latency_ms": 12.3,                  # 该阶段耗时（1 位小数）
      "output_count": 6,                   # 该阶段输出的候选数
      "results": [                         # 按排名升序的完整候选（不截断，便于横向对比）
        {"doc_id": "...", "rank": 1, "score": 0.83, "doc": DOC_VIEW | None}
      ]
    }
  ],
  "final": {"source": "rerank", "doc_ids": ["..."], "count": 3, "results": [ /* 同 results 结构 */ ]},
  "logs": [ {"stage","label","content","timestamp","is_error","error_msg"} ]
}
```

### 2.3 阶段语义（必须严格实现，前端按此展示）

| 勾选组合 | 实际执行 | `final.source` |
|---|---|---|
| 只勾 dense | 优化 → dense | `dense` |
| 只勾 bm25 | 优化 → bm25 | `bm25` |
| 只勾 rrf | 优化 → dense + bm25 → RRF | `rrf` |
| 只勾 rerank | 优化 → dense + bm25 → RRF → rerank | `rerank` |
| dense + rerank | 优化 → dense → rerank | `rerank` |
| bm25 + rerank | 优化 → bm25 → rerank | `rerank` |
| dense + bm25（无 rrf/rerank） | 优化 → dense + bm25 → RRF 合并 | `rrf` |
| dense + bm25 + rrf + rerank | 优化 → dense + bm25 → RRF → rerank | `rerank` |

规则：
1. Query 优化：**任一阶段启用即执行**（BM25 需要 match_topics/keywords，dense 需要 search_query）。`optimize_prompt` 阶段 `results` 为空列表，结构化信息放 `logs` 与 `run` 里暴露的 `optimized`（见下）。
2. `rrf` 为融合开关：只要提供了多于一条召回链路（dense 与 bm25 同时启用），即使没有勾 rrf，也要融合（否则无法产出统一候选集）。此时 `stages` 里仍出现 `rrf` 阶段（前端需能展示）。
3. `rerank` 阶段输入 = 上游候选（dense / bm25 / rrf 的输出）经 `knowledge_loader.load_knowledge(ids)` 得到的 Document 列表；调用 `reranker.rerank_documents(query, docs, final_top_k, score_threshold)`。**注意：rerank 只对上游候选集重排，不做全库重排。**
4. `final.results` 为最终返回列表（rerank 时是重排后 top final_top_k；否则上游 top final_top_k，doc 字段尽量填充）。
5. 空输入/全不勾：抛 `ValueError("至少选择一种检索方式")`。
6. dense / bm25 同时启用时允许并发（threading），但 `stages` 顺序固定为 dense 在前。
7. 日志：`trace` 参数不为 None 时，每个阶段追加 `trace.add_trace(stage=..., label=..., content=...)`（内容为可 JSON 序列化的摘要：命中 ids、数量、耗时、topics/keywords、分数等）；`run()` 最后返回 `logs = trace.get_all_trace()`（若 trace 为 None 则返回 `[]`）。
8. 阶段内部异常不要吞掉：向上抛（API 层统一兜底为 500 + 日志）。

### 2.4 `DOC_VIEW`：文档视图（与 API 列表共用同一形状）

```python
def doc_to_view(doc: Document) -> dict:
    return {
        "doc_id": str, "title": str, "doc_type": "daily"|"weekly",
        "date": str, "source": str, "relative_path": str, "knowledge_path": str,
        "summary": str, "topic": list[str], "keywords": list[str],
        "emotion": dict, "problem": str|None, "analysis": str|None, "solution": str|None,
        "word_count": int, "content": str,
    }
```
`doc_to_view` 由 **api-dev 在 `api/retrieval_debug.py` 内实现**；pipeline 的 `doc` 字段直接放 `Document` 对象或 `None` 均可，由 api-dev 在组装响应时统一调用 `doc_to_view`（pipeline 不依赖 api 层）。

## 3. FastAPI 契约（`api/retrieval_debug.py`，`router = APIRouter(prefix="/retrieval", tags=["检索优化调试"])`）

`main.py` 需 import 并 `app.include_router(retrieval_debug.router)`（放在 `app.mount("/")` 之前）。

### 3.1 `POST /retrieval/debug`

请求体（pydantic `RetrievalDebugReq`，全部可选）：

```json
{
  "query": "最近总是内耗，怎么和自己和解",
  "dense": true, "bm25": true, "rrf": true, "rerank": true,
  "raw_top_k": 6, "final_top_k": 3, "rrf_k": 60, "score_threshold": null
}
```
约束：`query` 必填非空；`raw_top_k`/`final_top_k` ∈ [1,50]；`rrf_k` ∈ [1,1000]；`score_threshold` ∈ [0,1] 或 null。

响应（统一 `api/common.py` 的 `resp()` 包裹）：

```json
{
  "code": 200, "msg": "检索调试完成", "extra": {},
  "data": {
    "query": "...",
    "flags": {"dense": true, "bm25": true, "rrf": true, "rerank": true},
    "params": {"raw_top_k": 6, "final_top_k": 3, "rrf_k": 60, "score_threshold": 0.08},
    "enabled_pipeline": ["optimize_prompt", "dense", "bm25", "rrf", "rerank"],
    "optimized": {"search_query": "...", "match_topics": [...], "keywords": [...]},
    "stages": [ /* 契约 2.2，doc 已替换为 DOC_VIEW */ ],
    "final": {"source": "rerank", "count": 3, "doc_ids": [...], "results": [...]},
    "latency_ms": 123.4,
    "logs": [ /* 契约 2.2 的 logs */ ]
  }
}
```

- 每阶段 `results[].doc` 用 `doc_to_view` 填充（rerank 阶段无 Document 时填 `null`）。
- `optimized` 取自 `optimize_prompt` 阶段的内部结果（api 层可以通过 pipeline 返回的 stages 之外单列：**约定 pipeline 在 `stages[0].extra` 里放 `{"search_query","match_topics","keywords"}`**，api 层直接透传为 `data.optimized`；若缺失则给空结构）。
- 参数校验失败返回 `CODE_PARAM_ERR(400)`；内部异常由 `@catch_exception` 兜底（500）。

### 3.2 `GET /retrieval/documents`

可视化「所有文档」。Query 参数：`keyword`(可选，模糊匹配 title/summary/content/keywords)、`doc_type`(daily|weekly)、`limit`(默认 200，[1,500])、`offset`(默认 0)。

```json
{"code":200,"msg":"加载知识库文档成功","data":{
  "total": 11, "count": 11, "offset": 0, "limit": 200,
  "doc_types": {"daily": 1, "weekly": 10},
  "documents": [ DOC_VIEW, ... ]}}
```
数据源：`KNOWLEDGE_CACHE.documents`（按 `date` 降序，date 为空排最后，同 date 按 title）。

### 3.3 `GET /retrieval/documents/{doc_id}`

返回单篇 `DOC_VIEW`（`data.document`）；不存在返回 `CODE_PARAM_ERR` + msg `文档不存在`。

### 3.4 `GET /retrieval/meta`

```json
{"code":200,"msg":"获取检索调试元信息成功","data":{
  "topics": ["Self_Understanding", ...],           // config.topic_config.VALID_TOPICS
  "doc_count": 11,
  "vector_count": 11,                                 // VectorDB.count()，异常时 null
  "bm25_ready": true,                                 // BM25_PATH.exists()
  "models": {"embedding": "bge-small-zh-v1.5", "reranker": "bge-reranker-base"},
  "defaults": {"raw_top_k": 6, "final_top_k": 3, "rrf_k": 60, "score_threshold": 0.08},
  "stages": [ {"name":"dense","label":"Dense 向量召回","desc":"..."}, ... ]  // 供前端渲染开关卡片
}}
```

## 4. 前端契约（`web-dev`）

- 新增左侧导航项 `data-view="retrieval"`，文案「检索调试 / Retrieval」；新增 `<section class="view" id="view-retrieval">`。
- 视图含四块（可用左右分栏）：
  1. **检索开关 + 参数**：dense / bm25 / rrf / rerank 四个可勾选卡片（说明各自含义）、raw_top_k / final_top_k / rrf_k / score_threshold 输入、prompt 文本框、`运行检索` 按钮、耗时与数量统计条。
  2. **全部文档**：默认展示 `GET /retrieval/documents` 全量（数量、daily/weekly 统计、关键词过滤框、类型过滤、点击卡片展开详情/正文，展开时懒加载 `GET /retrieval/documents/{doc_id}`）。
  3. **检索结果**：按 `data.stages` 渲染逐阶段卡片（阶段名、耗时、候选数、排名列表：名次/分数/标题/摘要/命中 topic），并高亮 `data.final` 的最终结果；每阶段结果可折叠。
  4. **检索日志**：渲染 `data.logs`（stage / label / 时间 / content 键值或 JSON），并给出运行摘要（enabled_pipeline、optimized 的 search_query/topics/keywords）。
- JS 侧在 `API` 常量对象里追加：`retrievalDebug: '/retrieval/debug'`、`retrievalDocs: '/retrieval/documents'`、`retrievalMeta: '/retrieval/meta'`。
- 在 `init()` 中调用 `bindRetrieval()`，并在初始化 `Promise.allSettled([...])` 中加载 `loadRetrievalMeta()` 与 `loadRetrievalDocs()`。
- 全部使用现有样式体系（`.view`/`.view-head`/`.btn`/`.results-list`/`.card` 等既有类名风格，必要时在 `style.css` 追加样式，类名前缀统一 `rd-`）。
- 不需要改动 `/trace/stream`（调试日志随 `POST /retrieval/debug` 响应返回）。

## 4.5 验证期间发现并修复的环境缺陷（Lead 记录）

`config/id_map.json` 中原有 11 条 **Windows 绝对路径**（`C:\Users\lilex\...`），在本机（macOS）
`os.path.exists` 全部为 False，导致 `KnowledgeLoader.load_knowledge()` 静默返回 `[]`，
进而使**生产链路** `Retriever.retrieve()` 的 rerank 输入恒为空（返回空文档列表）。

修复（`core/loader/knowledge_loader.py`，Lead 实施）：
1. `__init__` 增加 `_paths_usable()` 自愈判断：id_map 缺失 **或** 其中记录的路径在本机至少有一条不存在 → 自动 `_rebuild_id_map()` 就地重建；
2. `load_knowledge()` 用 `self.data.get(id)` 取路径，缺失 id 跳过并写 error 级 trace，不再抛 `KeyError` 打断整条检索。

修复后 `config/id_map.json` 已自动重建为本机绝对路径（11/11 可解析），
`Retriever.retrieve()` 与 `RetrievalPipeline._load_documents()` 均走主路径命中文档；
`retrieval_pipeline.py` 中保留的 `KNOWLEDGE_CACHE` 兜底分支作为二次保险（正常不再触发）。

## 5. 验收标准

1. `POST /retrieval/debug` 在 8 种勾选组合下均返回 200，`stages` 与 `final.source` 符合 §2.3 表格。
2. `final.results` 的 `doc_id` 顺序与同组合下直接调用流水线一致；`logs` 非空且包含每个已执行阶段。
3. `GET /retrieval/documents` 返回 11 篇文档（`total` 与 `KNOWLEDGE_CACHE` 长度一致），`doc_id` 唯一。
4. `web/index.html` / `web/app.js` 语法校验通过（`node --check web/app.js`），新视图可正常切换与渲染。
5. 生产链路未被破坏：`core/helper/retriever.py` 与 `core/helper/RAG_agent.py` 行为不变（未被修改）。
