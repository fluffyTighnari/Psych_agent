# 检索优化调试台（Retrieval Debug Console）

一个用于**手动编排检索链路、观察每一阶段召回效果**的调试系统，供你迭代检索逻辑（换模型、调权重、调 top_k、调阈值）时快速做 A/B 对比。

## 1. 启动

```bash
# 仓库根目录
.venv/bin/python main.py            # http://127.0.0.1:8000
```

> 首次打开「检索调试」并点击「运行检索」时，后端会懒加载本地 embedding / reranker 模型，
> 首次运行约 20~40 秒（之后同一进程内复用，单次 1~3 秒）。前端按钮在请求期间会显示「检索中…」。

前端页面：<http://127.0.0.1:8000/> → 左侧导航「**检索调试 / Retrieval**」。

## 2. 能做什么

| 能力 | 说明 |
|---|---|
| 任意组合检索链路 | Dense 向量召回 / BM25 关键词召回 / RRF 倒数排名融合 / Cross-Encoder 重排，四个开关独立勾选 |
| 手动输入 prompt | 直接输入问题，观察 Query 优化结果（search_query / match_topics / keywords） |
| 全部文档可视化 | 展示知识库全部文档（当前 11 篇），支持关键词与类型过滤、点击展开正文/problem/analysis/solution |
| 最终检索结果（置顶） | 所选链路最终返回的 Top-K：名次圆标、标题、类型/日期、分数、摘要、短 doc_id；标题旁显示「来源 · 条数」 |
| 逐阶段检索结果 | 每个阶段一张折叠卡片：耗时、候选数、排名 + 分数 + 标题 + 摘要 + topic；命中最终集的候选标「最终」 |
| 结构化检索日志 | 与 `/trace/stream` 无关的本次运行日志（阶段 / 标签 / 时间 / 结构化 content），含命中 ids、分数、阈值等 |
| 参数调节 | raw_top_k（召回数）、final_top_k（最终返回数）、rrf_k（融合常数）、score_threshold（重排阈值，留空用默认 0.08） |

> 结果栏布局：**「最终检索结果」（置顶）→「检索结果 · 逐阶段」→「检索日志」**；窄屏（≤720px）下排名行自动改为两行式（名次+分数一行、正文独占一行）。

## 3. 链路语义（勾选组合 → 实际执行）

| 勾选 | 实际执行 | 最终结果来源 |
|---|---|---|
| 只勾 Dense | 优化 → Dense | `dense` |
| 只勾 BM25 | 优化 → BM25 | `bm25` |
| 只勾 RRF | 优化 → Dense + BM25 → RRF | `rrf` |
| 只勾 Rerank | 优化 → Dense + BM25 → RRF → Rerank | `rerank` |
| Dense + Rerank | 优化 → Dense → Rerank | `rerank` |
| BM25 + Rerank | 优化 → BM25 → Rerank | `rerank` |
| Dense + BM25 | 优化 → Dense + BM25 → RRF 合并 | `rrf` |
| 全勾 | 优化 → Dense + BM25 → RRF → Rerank | `rerank` |

规则：`RRF` 是融合开关，只要同时勾了 Dense 与 BM25 就会自动融合（不勾 RRF 也融合，否则无法产出统一候选集）；
`Rerank` 只对**上游候选集**重排，不会全库扫描。算法与生产链路 `core/helper/retriever.py` 完全一致
（RRF `1/(pos+k)`、BM25 token = `jieba(query) + match_topics + keywords`、dense 文本 = `search_query + query`）。

## 4. API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/retrieval/debug` | 执行可配置检索流水线，返回 `stages` / `final` / `logs` / `optimized` |
| GET | `/retrieval/documents` | 知识库全量文档（`keyword` / `doc_type` / `limit` / `offset`） |
| GET | `/retrieval/documents/{doc_id}` | 单篇文档详情 |
| GET | `/retrieval/meta` | 主题集合、文档/向量计数、模型名、默认参数、阶段说明 |

```bash
curl -s http://127.0.0.1:8000/retrieval/debug \
  -H 'Content-Type: application/json' \
  -d '{"query":"最近总是内耗，怎么和自己和解","dense":true,"bm25":true,"rrf":true,"rerank":true,
       "raw_top_k":6,"final_top_k":3,"rrf_k":60,"score_threshold":null}' | python -m json.tool
```

响应（截断）：

```json
{"code":200,"msg":"检索调试完成","data":{
  "query":"...","flags":{...},"params":{...},
  "enabled_pipeline":["optimize_prompt","dense","bm25","rrf","rerank"],
  "optimized":{"search_query":"...","match_topics":["Self_Acceptance", "..."],"keywords":["内耗","和解"]},
  "stages":[{"name":"dense","label":"向量召回(Dense)","latency_ms":2659.5,"output_count":6,
             "results":[{"doc_id":"...","rank":1,"score":0.63,"doc":{...}}]}, "..."],
  "final":{"source":"rerank","count":3,"doc_ids":["..."],"results":[...]},
  "latency_ms":22300.0,
  "logs":[{"stage":"dense","label":"稠密向量检索完成","content":{...},"timestamp":1.7e9,"is_error":false}]}}
```

## 5. 代码结构（新增，不改动生产链路）

| 文件 | 作用 |
|---|---|
| `core/helper/retrieval_pipeline.py` | 可配置流水线：组件懒加载单例 + `RetrievalPipeline.run()`；`run_pipeline()` 便捷入口 |
| `api/retrieval_debug.py` | 4 个调试接口（统一 `resp()` / `catch_exception` 风格） |
| `main.py` | `include_router(retrieval_debug.router)`（在静态页 mount 之前） |
| `web/index.html` / `web/app.js` / `web/style.css` | 「检索调试」视图（原生 JS，无新依赖） |
| `scripts/verify_retrieval_debug.py` | 端到端验证脚本（TestClient + 8 种组合 + 交叉验证） |
| `docs/retrieval_debug_contract.md` / `docs/retrieval_debug_verify.md` | 接口契约 / 复核报告 |

`core/helper/retriever.py` 未被修改，生产对话链路仍走原有 `Retriever.retrieve()`。

### 5.1 日志隔离（重要）

检索调试的日志**不会**进入主对话的「实时流程日志」：

- 调试请求内用 `use_tracker(局部 TraceTracker)` 建立请求级上下文；`TraceTracker.add_trace` 会把
  本请求内**任何**写 `GLOBAL_TRACKER` 的既有组件（组件首次懒加载、reranker、BM25、knowledge loader …）
  自动改写进这个局部实例（`core/helper/trace_tracker.py` 的 `ContextVar` + `current_tracker()`），
  因此调试时 `/trace/all`、`/trace/stream` 保持为空；
- 局部上下文通过 `contextvars` 在 `run_in_executor` / 子线程中自动复制，天然按请求隔离；
- 调试请求结束后 `use_tracker_reset` 还原，**不影响**生产对话继续写全局日志。

「流程日志」页另做了两点改进以解决「显示不全」：

1. `/trace/all` 与 `/trace/stream` 现在携带 `version`（后端每次 `clear_trace` 自增）。前端发现版本变化时
   自动清空旧条目再渲染新一轮，避免上一轮日志与新日志混排、去重误伤；
2. 头部新增「**清空视图**」按钮，可手动清掉页面上的日志列表（只清视图，不动后端日志）。

每轮对话开始时后端会清空全局日志（`api/chat.py`），所以实时日志展示的是**本轮完整流程**。

## 6. 顺带修复的问题（与调试台同时生效）

| 文件 | 问题 | 修复 |
|---|---|---|
| `core/loader/knowledge_loader.py` | `config/id_map.json` 里存的是 Windows 绝对路径，本机解析失败 → `load_knowledge()` 静默返回 `[]`，**生产 rerank 输入恒为空** | 新增 `_paths_usable()` 自愈：路径全不可用时就地重建 id_map；`load_knowledge()` 缺失 id 跳过并记 trace，不再抛 `KeyError` |
| `core/helper/prompt_optimizer.py` | Query 改写每次真实调 LLM 且无缓存，同一 prompt 重复实验 `optimized` 会漂移 | 新增 TTL 30 分钟 + LRU 256 的进程内缓存（`cache_clear()` 可失效）：同一 prompt 多次运行结果一致，二次运行明显更快 |
| `core/helper/reranker.py` | `rerank_documents(..., score_threshold)` 形参被忽略，始终用实例默认阈值 | 显式传入时以传入值为准；不传时行为不变（生产默认路径无差异），调试台可真实对比不同阈值 |

修复后已重跑验证脚本：**256 项断言 PASS / 0 FAIL**（`scripts/verify_retrieval_debug.py`）。
