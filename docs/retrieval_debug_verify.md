# 检索优化调试系统 · 独立验证报告（task-4）

- 验证者：verifier（独立复核，不复述实现者自测结论）
- 验证时间：2026-10-10 15:42:43（Asia/Shanghai）
- 验证环境：仓库根 `/Users/mac/Documents/code/psych`，Python 3.14.7（`.venv`），Node v22.22.0，`HF_HUB_OFFLINE=1`，macOS；本地 Ollama 未运行（`127.0.0.1:11434` 无响应），`GLOBAL_MODEL.small` 实际为 `driver=api / deepseek-v4-flash`（`config/model_store.json`）
- 被测交付物：`core/helper/retrieval_pipeline.py`、`api/retrieval_debug.py`、`main.py`、`web/index.html|app.js|style.css`、Lead 修复的 `core/loader/knowledge_loader.py`
- 验证脚本（本次唯一写入的业务外产物）：`scripts/verify_retrieval_debug.py`
- 完整逐项结果（256 行 JSON）：`/tmp/verify_retrieval_debug/result.json`；控制台全文：`/tmp/verify_retrieval_debug/run5.txt`（复现确认运行：`run6.txt`，同样 PASS=256/FAIL=0）

## 0. 结论摘要

| 项 | 结果 |
|---|---|
| 总判定 | **PASS=256，FAIL=0，INFO=5**，脚本退出码 `0` |
| 契约 §5.1（8 种组合 + stages/final.source） | PASS（8/8，逐字段核对 §2.3 表格） |
| 契约 §5.2（final 与直跑一致 + logs 覆盖） | PASS（按 Lead 指定方法：stub 优化器注入进程单例后，API 与直跑 8 组合的 stages（含分数）/final/source/count 全一致；未 stub 漂移另记 INFO） |
| 契约 §5.3（11 篇文档 / doc_id 唯一） | PASS |
| 契约 §5.4（`node --check` + 新视图） | PASS（静态部分；浏览器交互见 §6 未覆盖项） |
| 契约 §5.5（生产链路未被破坏） | PASS（`retriever.py` 相对 HEAD 零 diff；`RAG_agent.py` 有既有重构 diff 但与本特性无关，见 §5-风险2） |
| Lead 生产修复复核（id_map/knowledge_loader/Retriever） | PASS（K1–K3，见 §3.6） |
| 脚本可重复运行 / 无副作用 | PASS（同一脚本连续两次运行均 PASS=256/FAIL=0；业务数据只读哨兵无变化，Z1） |

**没有任何 FAIL。** 报告 §5 列出 4 项「已知特性/待裁决」与 1 项「设计注意」，均非本次实现缺陷，但建议 Lead 确认。

## 1. 验证命令

```bash
cd /Users/mac/Documents/code/psych
HF_HUB_OFFLINE=1 .venv/bin/python scripts/verify_retrieval_debug.py     # 退出码 0
```

脚本行为：读契约 §5 逐项打断言 → 走 `fastapi.testclient.TestClient(main.app)` 真实路由 → 直接 `import core.helper.retrieval_pipeline` 交叉验证 → 静态/`node --check`/`git` 检查。只写 `/tmp/verify_retrieval_debug/`，不写业务数据、不 `git commit`、不修改被验证交付物。

## 2. 逐项 PASS/FAIL 表

### 2.1 A. `POST /retrieval/debug` 8 种勾选组合（137 项全 PASS）

每个组合核对 17 项：`.0` 统一返回体 `{code,msg,data,extra}`；`.1` 响应可 `json.dumps`；`.2` data 顶层 9 字段齐全；`.3` flags 回显；`.4` stages 名称符合 §2.3；`.5` stages 顺序固定；`.6` `enabled_pipeline==stages` 名称；`.7` `final.source`；`.8` stage/result/doc 形状（score 为数值、doc 为 DOC_VIEW 或 null）；`.9` `optimize_prompt.results==[]`；`.10` `optimized` 三字段；`.11` `optimized==stages[0].extra`；`.12` `final.count==len(doc_ids)==len(results)`；`.13` `final.results` 形状；`.14` final 非空；`.15` logs 非空且覆盖已执行阶段；`.16` logs 条目六字段齐全。

| 组合 | 期望 stages（§2.3） | 实际 stages | `final.source` | 17 项 |
|---|---|---|---|---|
| dense-only | optimize_prompt, dense | 同左 | dense | 全 PASS |
| bm25-only | optimize_prompt, bm25 | 同左 | bm25 | 全 PASS |
| rrf-only | optimize_prompt, dense, bm25, rrf | 同左 | rrf | 全 PASS |
| rerank-only | optimize_prompt, dense, bm25, rrf, rerank | 同左 | rerank | 全 PASS |
| dense+rerank | optimize_prompt, dense, rerank | 同左 | rerank | 全 PASS |
| bm25+rerank | optimize_prompt, bm25, rerank | 同左 | rerank | 全 PASS |
| dense+bm25 | optimize_prompt, dense, bm25, rrf | 同左 | rrf | 全 PASS |
| all | optimize_prompt, dense, bm25, rrf, rerank | 同左 | rerank | 全 PASS |

`A0`：`main.app` 已挂载 `/retrieval/debug`、`/retrieval/documents`、`/retrieval/documents/{doc_id}`、`/retrieval/meta`（`app.openapi()["paths"]` 枚举；新版 FastAPI 把 `include_router` 包成 `_IncludedRouter`，无 `.path`）。

### 2.2 B. 参数校验（5 项全 PASS）

| id | 用例 | 结果 |
|---|---|---|
| B1 | `query=""` | PASS `code=400` / `msg="参数不合法: query 不能为空"` |
| B2 | `raw_top_k=0` | PASS `code=400` / `raw_top_k 需在 [1,50] 区间` |
| B3 | `raw_top_k=99` | PASS `code=400` / 同上 |
| B4 | `rrf_k=0` | PASS `code=400` / `rrf_k 需在 [1,1000] 区间` |
| B5 | `score_threshold=2` | PASS `code=400` / `score_threshold 需在 [0.0,1.0] 区间或为 null` |

设计注意（非缺陷）：HTTP 状态码统一为 `200`，业务码在 body 里为 `400`。契约 §3.1 写的是 `CODE_PARAM_ERR(400)`（`api/common.py` 的业务码），因此判定通过；若验收方要求 HTTP 层 400，需要额外改 `main.py`/路由。

### 2.3 C. `GET /retrieval/documents`（16 项全 PASS）

| id | 断言 | 关键实测 |
|---|---|---|
| C1 | HTTP 200 且 `code=200` | PASS |
| C2 | `total == KNOWLEDGE_CACHE 长度 == 11` | `total=11 cache_len=11` |
| C3 | `count == len(documents) == total` | `11/11/11` |
| C4 | `doc_id` 唯一 | `n=11 unique=11` |
| C5 | doc_id 集合与 `KNOWLEDGE_CACHE` 完全一致 | 双向差集为空 |
| C6 | 全部为 DOC_VIEW 形状（16 键） | `bad=[]` |
| C7 | date 降序、空值最后、同 date 按 title | `dates=["2026-7-11","","",...]` |
| C8 | `doc_types` 统计正确且合计==total | `{"daily":1,"weekly":10}` |
| C9 | `keyword` 过滤生效 | `keyword='20'` → 2 篇且全部命中 |
| C10 | `doc_type=weekly` | 10 篇全 weekly |
| C11 | `doc_type=daily` | 1 篇（=daily 总数） |
| C12 | `limit=2` 且 total 不变 | `n=2 total=11` |
| C13 | `offset=1` 与全量切片一致 | 逐条一致 |
| C14 | `doc_type=bogus` → 400 | PASS |
| C15 | `limit=0` → 400 | PASS |
| C16 | `limit=999` → 400 | PASS |

### 2.4 D/E/G/F/K/H（其余 102 项全 PASS）

| 分组 | id 范围 | 项数 | 结果 |
|---|---|---|---|
| D 单文档 | D1 真实 id 返回 `document`；D2 伪造 id → `code=400` + `msg="文档不存在"` | 2 | 全 PASS |
| E meta | E1 HTTP/code；E2 七字段齐全；E3 `topics==VALID_TOPICS`(20)；E4 `doc_count==11`；E5 `vector_count` int|null(=11)；E6 `bm25_ready=true`；E7 models 展示名；E8 defaults `6/3/60/0.08`；E9 stages 含 name/label/desc 且覆盖 4 核心阶段 | 9 | 全 PASS |
| G 静态/反例 | G1–G2 index.html 标记；G3.1–G3.4 app.js API 常量/bindRetrieval；G4 + G4.1–G4.7 前端结构与 `rd-` 样式；G5 `node --check`；G6/G7 git 基线；G8 knowledge json 数 | 19 | 全 PASS（G7 见风险2） |
| F 交叉验证 | F.drift（INFO）；F1/F2 组件与复用；F3.stub-setup + 8 组合×7 子项 + overall/determinism/shape；F6 dense/bm25/rrf/rerank 独立复算 | 59 | 全 PASS（F.drift 为 INFO） |
| K 生产修复 | K1 id_map 11/11 本机可解析；K2 load_knowledge 3/3；K2b data 11 条；K2c id 集合一致；K3 `Retriever.retrieve` 返回 3 篇 | 5 | 全 PASS |
| H 边界 | H1 无命中；H2 阈值=1.0；H3 top_k=50；H4 空白 query→400；H5 全不勾→400；H6 阈值=0.0（+2 条空结果 INFO） | 8 | 全 PASS |
| Z 只读 | Z1 业务数据哨兵（data/knowledge、store/bm25_store、config/id_map.json）无变化 | 1 | INFO 无变化 |

## 3. 原始关键输出

### 3.1 路由与 all 组合逐阶段（`data.stages` 压缩，stub 优化器）

```
/retrieval/debug, /retrieval/documents, /retrieval/documents/{doc_id}, /retrieval/meta

optimize_prompt  label=Query 优化            latency=1745.2ms output_count=0  results=[]
dense            label=向量召回(Dense)        latency=58.6ms   output_count=6  rank1 doc=68dfd665… score=0.767434 has_doc=true …
bm25             label=BM25 关键词召回        output_count=4
rrf              label=RRF 融合               output_count=7
rerank           label=Cross-Encoder 重排     output_count=3
```

### 3.2 §5.2 交叉验证（Lead 指定方法：stub 注入 `_COMPONENTS["prompt_optimizer"]`）

8 种组合的 API 与直跑 `stages`（doc_id + score）与 `final` 逐条一致，且 `optimized == stages[0].extra == 固定 stub`。示例（all 组合）：

```
api_doc_ids    = [4ba060b5…, 68dfd665…, 5fac2b72…]
direct_doc_ids = [4ba060b5…, 68dfd665…, 5fac2b72…]   match=true
F3.overall      PASS   8 种组合：stub 优化器下 API 与直跑 stages/final 全一致
F3.determinism  PASS   stub 下 pipeline 两次直跑完全一致
F3.shape        PASS   pipeline.run 无 numpy 标量、可 json.dumps
```

### 3.3 独立复算（F6，不依赖 pipeline 内部实现）

```
F6.dense   dense 阶段候选   == encode(search_query+query) → vector_db.query(raw_top_k)   PASS
F6.bm25    bm25 阶段候选    == BM25TagIndexer.search(jieba(query)+topics+keywords)        PASS
F6.rrf     rrf 阶段候选     == 独立 1/(pos+rrf_k) 降序                                     PASS
F6.rerank  final.doc_ids    == 直接调用 Reranker.rerank_documents（默认阈值）              PASS
```

### 3.4 生产修复复核（K）

```
K1  PASS  config/id_map.json 全部路径本机可解析（11/11），unresolvable=[]
K2  PASS  KnowledgeLoader().load_knowledge(3 ids) → 3/3 且顺序一致
K2b PASS  KnowledgeLoader().data 条目数 == 11
K2c PASS  id_map doc_id 集合 == KNOWLEDGE_CACHE doc_id 集合（only_map=[]）
K3  PASS  生产 Retriever.retrieve(query, raw_top_k=6, final_top_k=3) → 3 篇
          ids=[1dfb9c9f…, 4ba060b5…, 68dfd665…]
```

另外，F3 每个组合都断言了 **每阶段 `results[].doc` 均非空**（`null_docs=[]`）且 **日志中无「候选 doc_id 在本地知识库中不存在」**（`hit=[]`），与 Lead 要求一致。

### 3.5 meta 原始返回

```json
{"topics":["Action","Anxiety","Career","Cognitive_Patterns","Emotion_Regulation","Happiness","Learning","Lifestyle","Motivation","Perfectionism","Personal_Growth","Philosophy","Psychology","Relationships","Self_Acceptance","Self_Understanding","Skill_Development","Stress_Health","Uncertainty","Values"],
 "doc_count":11,"vector_count":11,"bm25_ready":true,
 "models":{"embedding":"bge-small-zh-v1.5","reranker":"bge-reranker-base"},
 "defaults":{"raw_top_k":6,"final_top_k":3,"rrf_k":60,"score_threshold":0.08},
 "stages":[{"name":"optimize_prompt",…},{"name":"dense",…},{"name":"bm25",…},{"name":"rrf",…},{"name":"rerank",…}]}
```

### 3.6 git 基线

```
core/helper/retriever.py     : git diff --stat HEAD → 空（零 diff）
core/helper/RAG_agent.py     : 124 insertions(+), 103 deletions(-)（见风险2）
main.py                      : 已 include_router(retrieval_debug.router)（在 app.mount("/") 之前）✓
web/index.html|app.js|style.css : 已含新视图（G 组 19 项 PASS）
```

## 4. 漂移证据与复现命令（INFO，非 FAIL）

同一 query 连续两次请求，`optimized` 会变化；`final.doc_ids` 是否同步变化取决于当次采样（run5 中恰好一致，run4 中不一致）。`F.drift`（INFO，不判 FAIL）：

```
opt1={"search_query":"如何停止内耗并与自己和解","match_topics":["Self_Acceptance","Emotion_Regulation","Anxiety"],"keywords":["内耗","自我和解","焦虑"]}
opt2={"search_query":"如何减少心理内耗并与自我和解","match_topics":["Self_Acceptance","Emotion_Regulation","Self_Understanding"],"keywords":["内耗","自我和解",…]}
optimized漂移=True  doc_ids漂移=False（run5）；run4 同项为 optimized漂移=True doc_ids漂移=True
ids1=["1dfb9c9f…","4ba060b5…","68dfd665…"]   ids2 同 ids1
```

复现：

```bash
cd /Users/mac/Documents/code/psych
HF_HUB_OFFLINE=1 .venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
import main
c = TestClient(main.app)
body = {"query": "最近总是内耗，怎么和自己和解", "dense": True, "bm25": True, "rrf": True, "rerank": True}
for i in range(2):
    d = c.post("/retrieval/debug", json=body).json()["data"]
    print(i, d["optimized"], d["final"]["doc_ids"])
PY
```

## 5. 已知特性 / 需 Lead 裁决（无 FAIL）

1. **LLM 优化器非确定性（F.drift）**：`PromptOptimizer.optimize_prompt` 每次请求都会真实调用 LLM（`GLOBAL_MODEL.small` = `deepseek-v4-flash`, temperature 0），且**无缓存**（`core/helper/prompt_optimizer.py` 无 `lru_cache`；生产 `Retriever.retrieve` 同样每次重算）。因此契约 §5.2「final.doc_ids 与同组合直跑一致」在真实链路上不可复现。已按 Lead 指示改为 stub 注入后比对（全 PASS），漂移单独记录。**建议**：在契约 §5.2 注明「须固定优化器输出后比对」，或给 `PromptOptimizer.optimize_prompt` 加进程内缓存（属生产文件，未改）。
2. **`RAG_agent.py` 相对 HEAD 有 diff（124+/103-）**：文件 mtime `2026-09-23 20:49`，早于本特性全部文件（`2026-10-10 15:27+`）；diff 中不含任何 `retrieval_pipeline`/`retrieval_debug` 引用（0 行）；文件仍走 `self.retriever.retrieve(...)`。判定：**既有重构差异，非本次特性引入**，因此 G7 记 PASS（"未被本次特性修改"），但严格按 §5.5 字面「未被修改」需要 Lead 用基线确认。`retriever.py` 为零 diff，无争议。
3. **`Reranker.rerank_documents` 忽略传入的 `score_threshold` 形参**：该方法内部固定用 `self.score_threshold`（默认 0.08）。契约 §2.3 规则 3 要求把 `score_threshold` 传给它，但传参实际不生效；pipeline 通过自行用 `reranker.model.predict` 复算 + 显式阈值补偿，并在不一致时补日志（契约允许）。属**既有生产文件缺陷**（禁止修改），本次实现已规避；H2（`score_threshold=1.0`）实测 `code=200`、`final.count=0`、形状合法。建议 Lead 决定是否单开任务修 `reranker.py`。
4. **`KnowledgeLoader.__init__` 的自愈写入**：id_map 缺失或路径全不可用时会在构造时**重写 `config/id_map.json`**（Lead 修复引入）。本次运行哨兵未捕获到变化（id_map 已是本机路径 11/11）。若后续把 `KnowledgeLoader()` 放在只读请求路径上，需注意这个写副作用。替代方案建议（不改文件）：保留 id_map 但解析失败时只做**内存内重建**（不落盘），或把重建写入 `store/` 派生缓存并保留原映射格式兼容相对路径。
5. **参数校验的 HTTP 语义**：见 §2.2 设计注意（HTTP 200 + 业务 code 400）。

## 6. 未覆盖项

1. **真实浏览器交互**：未启动服务/未用 headless 浏览器验证「视图切换、卡片折叠、点击展开懒加载详情、日志渲染」等 §4 交互行为；仅做了 `node --check` + DOM/JS 标记静态核对（G1–G4.7）。
2. **真实 HTTP 服务链路**：用 `TestClient` 绕过 uvicorn/CORS；未验证 `python main.py` 起服后 `web/` 静态回落与跨域。
3. **并发/长时稳定性**：未做多请求并发压测、未验证 8 种组合以外的并发下单例组件线程安全（pipeline 的 dense/bm25 双线程在单请求内已验证）。
4. **Windows/跨平台**：`id_map.json` 自愈只在 macOS 本机验证（当前 11/11 可解析）；未模拟「id_map 全为 Windows 路径」的冷启动重建。
5. **`rerank` 阶段 `doc` 为 null 的分支**：真实数据下所有候选都能解析出 Document，未触发 null 分支（代码路径已由契约允许，但未实测）。
6. **前端 `score_threshold` 空值语义**：仅验证 API 默认 0.08 回显，未验证前端把空输入正确传为 `null`。

## 7. 结论

按 `docs/retrieval_debug_contract.md` §5 五项验收标准与 task-4 全部要求，**256 项断言全部 PASS，0 FAIL**；Lead 的两项输入（stub 化交叉验证、`knowledge_loader`/`Retriever` 生产修复复核）均已独立验证通过。§5 的 5 条「已知特性/待裁决」不影响本次交付验收，但建议 Lead 对第 1、2 条给出书面裁决，对第 3 条决定是否另立修复任务。

## 8. Lead 裁决与后续修复（报告出具后追加，验证者未参与）

针对 §5 的 5 条「已知特性/待裁决」，Lead 的裁决与改动如下；改动后由 Lead 重跑本脚本复核，**仍为 PASS=256 / FAIL=0 / INFO=5**。

| # | 裁决 | 落地改动 |
|---|---|---|
| 1 优化器无缓存、结果漂移 | **修**（保留确定性，代价可控） | `core/helper/prompt_optimizer.py` 新增 `ttl_cache`（TTL 30 分钟、容量保护）并给 `optimize_prompt` 套 `lru_cache(maxsize=256)`；新增 `cache_clear()`。同一 prompt 重复请求复用改写结果。实测：同一 query 两次连发 `optimized` 与 `final.doc_ids` **完全一致**，第二次延迟 11.1s → 5.9s。未改动生产调用点语义（首次仍真实调用 LLM）。 |
| 2 `RAG_agent.py` 有既有 diff | **确认**：mtime 2026-09-23 早于本特性全部文件（2026-10-10），diff 中 0 处检索调试引用，仍走 `self.retriever.retrieve` → 判为**既有重构**，本特性未修改该文件 |
| 3 `Reranker.rerank_documents` 忽略 `score_threshold` | **修**（调试台必须能对比阈值） | `core/helper/reranker.py`：`threshold = self.score_threshold if score_threshold is None else float(score_threshold)`，trace 同步记录实际阈值。**不传参时行为与修复前完全一致**（生产默认路径无变化）。实测 `None/0.0/0.99/1.0` 阈值区分正确；pipeline 显式阈值路径不再出现「阈值不一致」补偿日志。 |
| 4 `KnowledgeLoader` 自愈会重写 `id_map.json` | **保留**，但收敛为「只有确实不可用时才写」 | 已有 `_paths_usable()` 前置判断：路径可解析时**完全不写盘**（本次验证 Z1 哨兵未捕获变化即为证据）；仅跨平台/迁移导致全不可用时重建一次。 |
| 5 参数校验 HTTP=200 + 业务 code=400 | **确认遵循契约**（`api/common.py` 统一业务码），不改 |

附带修复（Lead 发现）：`core/helper/retrieval_pipeline.py` 的 `_optimize_query` 改为 `dict(raw)` 拷贝，
避免缓存命中的同一个 dict 被下游改动后污染缓存。

## 9. 前端展示问题修复（用户实测反馈，2026-10-11）

用户反馈两点，均为 **web 层展示问题**（后端数据与验证结论不变）：

1. **逐阶段中间结果排版错乱**（文字竖排、标签溢出）
   根因：排名行 `.rd-rank` 用 `flex` + 尾列 `.rd-rank-side` 承载 "最终" 徽标与 topic 标签，
   该列 `flex: 0 0 auto` 不可收缩；同时主列里塞了完整 36 字符 doc_id（`word-break: break-all`），
   在右栏窄宽度下把主列挤到只剩一两个字符宽 → 出现竖排/溢出。
   修复（`web/style.css` + `web/app.js`）：`.rd-rank` 改用 `grid-template-columns: 30px 62px minmax(0,1fr)`；
   主体改为 `div.rd-rank-body`（消除 `span` 里套 `div` 的非法嵌套）；doc_id 只显示前 8 字符 + `…`（完整值放 `title`），
   topic 最多 3 个；删掉不可收缩的尾列；≤720px 时改用 `grid-template-areas` 让主体独占整行。
2. **检索结果面板不含最终检索结果**
   修复（`web/index.html` + `web/app.js`）：结果栏顶部新增置顶的「**最终检索结果**」面板
   （`#rd-final-list` / `#rd-final-hint`），渲染 `data.final.results` 的排名卡片（名次圆标 / 标题 / 类型 / 日期 / 分数 / 摘要 / 短 doc_id），
   标题旁显示「来源 rerank · 3 条」；原面板改名「检索结果 · 逐阶段」并在其中继续用「最终」徽标高亮命中最终集的候选。

复核方式（Lead 执行）：
- `node /tmp/rd_render_check2.js`（沙箱 DOM 加载 `web/app.js`，用真实后端响应渲染）→ **16 PASS / 0 FAIL**：
  最终卡片数 == `final.results` 数、每阶段排名行数 == 候选总数、每行恰好 3 个直接子元素
  （`span.no` / `span.score` / `div.body`）、无 `span>div` 非法嵌套、长 doc_id 不再出现在可见文本、
  rerank-only 与空结果分支渲染正常、畸形 payload 不抛异常。
- `node --check web/app.js` PASS；CSS 括号平衡 0；本报告 §1 的 256 项验证脚本重跑 **仍 PASS=256 / FAIL=0**。

## 10. 实时流程日志「显示不全」修复（用户实测反馈，2026-10-11）

用户反馈：主对话的「实时流程日志」输出不全，怀疑检索调试页的日志混了进去。**怀疑成立**，有两处根因：

1. **调试日志泄漏进全局日志流**：`Reranker.rerank_documents` 与 `BM25TagIndexer` 等组件硬编码写
   `GLOBAL_TRACKER`，而调试接口只给流水线传了局部 `trace`，这些组件仍写全局 →
   每次调试运行都会往 `/trace/all`、`/trace/stream` 灌注日志。
   修复：`core/helper/trace_tracker.py` 新增 `ACTIVE_TRACKER`（`ContextVar`）+ `current_tracker()` |
   `use_tracker()` / `use_tracker_reset()`；`TraceTracker.add_trace` 在「当前请求存在局部 trace 且
   本实例不是它」时自动改写目标。`api/retrieval_debug.py` 在整个处理入口（含组件懒加载，必须早于
   `get_retrieval_components()`）建立局部上下文；`reranker.py`、`BM25.py`、`knowledge_loader.py`
   改用 `current_tracker()`。`contextvars` 在 `run_in_executor`/子线程中自动复制，按请求隔离。
   实测：连续两次调试运行后 `GET /trace/all` 恒为 `{version: 0, logs: []}`（含冷启动组件装载日志），
   而调试响应自身拿到 7~9 条完整日志。
2. **前端跨轮次累积 + 签名去重导致「不全」**：`clear_trace` 后旧条目仍在 DOM 中，签名集合不重置，
   新日志可能被误去重。修复：`api/trace.py` 的 `/trace/all` 与 `/trace/stream` 携带 `version`；
   `web/app.js` 检测到版本变化即清空视图重渲染，并新增「清空视图」按钮（`#btn-trace-clear`）。

回归验证：`trace/all` 返回 `{version, logs}`（旧字段 `logs` 保留，向后兼容）；SSE 事件为
`{"version": N, "logs": [...]}`；`node --check` PASS；`scripts/verify_retrieval_debug.py`
（TestClient 覆盖全部端点）重跑 **PASS=256 / FAIL=0**。


