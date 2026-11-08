# rag_optimize —— RAG 检索语义调优评测数据集（v2）

用于评估和优化 PsychAgent 的 RAG **语义**检索能力（`core/helper/retriever.py` / `core/helper/retrieval_pipeline.py`）。

## 设计原则（v2 相对 v1 的改动）

1. **Query 口语化**：每条问题都用日常语言描述场景 / 感受 / 行为，**刻意避开**文档标题词、topics 英文标签与 keywords 中的特色术语（如"后发性共情""防御性悲观""课题分离""三维标尺"等）。目标是：**纯字面 BM25 匹配无法可靠命中**，只有 Dense 向量检索 + Cross-Encoder 重排能正确召回。
2. **Multi ground-truth**：一个宽泛的咨询问题可能对应多篇语义有效文档。`target_doc_ids` 为有效文档集合（命中任一即算该条语义召回成功），`primary_target` 为最直接的单目标（用于严格口径统计）。
3. **Hard negatives**：语义相近、字面可能更接近、但**并未回答**该问题的文档，用于评估检索的区分度（与 `target_doc_ids` 互斥）。
4. **语义难点条目**：个别主题独特的问题（如"假如当初"）无任何字面关键词可匹配，只有 dense+rerank 链路能命中——用于验证语义链路是否真的工作。

## 数据内容

`rag_optimize.json` 共 **31 条**，覆盖知识库全部 31 篇文档（Daily 7 + Weekly 24）。每条记录字段：

| 字段 | 含义 |
|---|---|
| `query` | 口语化第一人称咨询问题（症状/场景化，无文档术语） |
| `primary_target` | 最直接的单目标文档 id（严格口径用） |
| `target_doc_ids` | 语义有效文档集合（multi ground-truth，2–3 篇） |
| `target_titles` | 上述文档标题（便于人读） |
| `rationale` | 语义对应关系说明 |
| `hard_negatives` | 易混淆但不应命中的文档 id 列表 |

## 评估方法

> **本数据集的最近一次优化结果见 [`docs/rag_optimization_report.md`](../docs/rag_optimization_report.md)**
> （v1 基线 loose@3 0.968 / strict@3 0.968 / MRR 0.952 / 「无效文档排在有效文档前」2 条
> → 优化后 1.000 / 1.000 / 1.000 / **0 条**）。

### 推荐：直接跑仓库里的评测脚本（不要手写）

```bash
# 端到端：真实 RetrievalPipeline + 当前默认参数（含逐项消融）
python -u scripts/rag_opt/eval_final.py

# 通过检索接口评测（需先起服务）
python -m uvicorn main:app --host 127.0.0.1 --port 8001
python -u scripts/rag_opt/eval_via_api.py http://127.0.0.1:8001

# 接口冒烟 + 契约校验
python scripts/rag_opt/verify_api.py http://127.0.0.1:8001
```

`scripts/rag_opt/harness.py` 实现了下面这套口径（比早期 README 的临时脚本多出
`cov@3`（覆盖度）、`neg_before`（无效文档排在有效文档之前的 query 数）、
`union_recall/union_full`（召回上限）三类指标）。

### 手工写法（等价，便于理解口径）

```python
from core.helper.retrieval_pipeline import run_pipeline
import json

ds = json.load(open("rag_optimize/rag_optimize.json", encoding="utf-8"))

def evaluate(pipeline_kwargs):
    loose = strict = neg_leak = 0
    for it in ds["items"]:
        res = run_pipeline(it["query"], final_top_k=3, **pipeline_kwargs)
        top = res["final"]["doc_ids"]
        if set(top) & set(it["target_doc_ids"]):
            loose += 1
        if it["primary_target"] in top:
            strict += 1
        for n in it["hard_negatives"]:
            if n in top:
                neg_leak += 1
    n = len(ds["items"])
    return f"Recall@3(loose)={loose}/{n}  Recall@3(strict)={strict}/{n}  neg_leak={neg_leak}"

print("full      :", evaluate(dict()))
print("dense only:", evaluate(dict(bm25=False, rrf=False)))
print("bm25 only :", evaluate(dict(dense=False, rrf=False)))
```

**判读**：
- `full` 的 loose Recall@3 应显著高于 `bm25 only`——否则说明 query 仍偏字面化，需要继续口语化改造；
- `bm25 only` 与 `dense only` 的对比可定位单路瓶颈（如 embedding 对情绪化口语的编码能力）；
- `neg_leak` 高说明相似文档间区分度不足（重排模式 / blend_alpha / rrf_k / 查询词权重需要调）。

### 方式二：网页调试页

启动服务后使用 `/api/retrieval_debug`（见 `docs/retrieval_debug_contract.md`），逐条输入 `query` 观察各阶段命中情况。
v2 起该接口新增 `w_dense` / `w_bm25` / `use_hyde` / `rerank_pool` / `rerank_mode` / `blend_alpha`
六个调优开关，且 `/retrieval/meta` 会回显当前 BM25 索引规格与默认参数。


## 指标口径

- **宽松 Recall@3（多目标）**：`final.doc_ids`（top-3）与 `target_doc_ids` 有交集即算命中 —— 语义召回的合理口径；
- **严格 Recall@3（单目标）**：top-3 含 `primary_target` —— 主命中能力；
- **hard-negative 泄漏**：`hard_negatives` 进入 top-3 的次数 —— 区分度指标；
- 可按 `target_type` 分组统计 daily / weekly 差异。

## 扩展建议

- 为每条 query 增加 1–2 个**变体**（更口语 / 更情绪化），提升鲁棒性覆盖；
- 接入回归：调 `raw_top_k` / `rrf_k` / `score_threshold` / topic、keyword 权重后重跑，对比三档指标；
- 新增知识文档时按相同结构补录（口语化 query + multi targets + hard_negatives）。