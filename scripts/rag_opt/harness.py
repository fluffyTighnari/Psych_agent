"""RAG 检索优化 · 评测工具库。

提供：
- load_dataset()           读取 rag_optimize/rag_optimize.json
- CachedOptimizer          PromptOptimizer 的磁盘缓存包装（避免重复调用 LLM，保证实验可复现）
- evaluate(...)            跑完整流水线并按多口径统计指标
- build_bm25(...)          按字段权重规格重建 BM25 索引（写到临时路径，不污染生产索引）
- build_vector_db(...)     按文档编码文本规格重建向量集合（写到临时目录，不污染生产向量库）

指标口径：
- loose@k       top-k 与 target_doc_ids 有交集（多有效文档口径）
- strict@k      top-k 含 primary_target
- mrr           1/rank(primary)，未命中记 0
- neg@k         hard_negatives 进入 top-k 的次数（越少越好）
- neg_before    存在「无效文档排在最优有效文档之前」的 query 数（越少越好）
- cov@k         所有 target_doc_ids 中被 top-k 覆盖的比例（覆盖度）
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

CACHE_DIR = Path(__file__).resolve().parent / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR = Path(__file__).resolve().parent / ".tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

DATASET_PATH = ROOT / "rag_optimize" / "rag_optimize.json"


def load_dataset() -> dict:
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ 优化器缓存
class CachedOptimizer:
    """包装 PromptOptimizer：按 (提示词版本, query) 落盘缓存改写结果。

    v2 起 optimizer 有两种提示词（lite / 完整 HyDE 版），缓存文件按 want_hyde 分开存放，
    避免两种提示词的结果互相串用。
    """

    def __init__(self, inner, prompt_version: str, name: str = "default", hyde_version: str | None = None):
        self.inner = inner
        self.prompt_version = prompt_version
        self.hyde_version = hyde_version or prompt_version
        self.name = name
        self.stores = {}
        self.hits = 0
        self.misses = 0

    def _store(self, want_hyde: bool):
        key = True if want_hyde else False
        if key not in self.stores:
            ver = self.hyde_version if want_hyde else self.prompt_version
            path = CACHE_DIR / f"opt_{self.name}_{ver}_{'hyde' if want_hyde else 'lite'}.json"
            store = {}
            if path.exists():
                try:
                    store = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    store = {}
            self.stores[key] = (path, store)
        return self.stores[key]

    def optimize_prompt(self, query: str, want_hyde: bool = False) -> dict:
        path, store = self._store(want_hyde)
        key = hashlib.md5(query.encode("utf-8")).hexdigest()
        if key in store:
            self.hits += 1
            return dict(store[key])
        self.misses += 1
        try:
            val = self.inner.optimize_prompt(query, want_hyde=want_hyde)
        except TypeError:
            val = self.inner.optimize_prompt(query)
        val = dict(val or {})
        val.setdefault("search_query", query)
        val.setdefault("match_topics", [])
        val.setdefault("keywords", [])
        store[key] = val
        path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
        return dict(val)

    def flush(self):
        for path, store in self.stores.values():
            path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ 指标
def score_query(item: dict, top_ids: list[str], final_doc_ids: list[str],
                union_ids: list[str] | None = None) -> dict:
    targets = list(item.get("target_doc_ids") or [])
    primary = item.get("primary_target")
    negs = list(item.get("hard_negatives") or [])

    top3 = final_doc_ids
    hit = [d for d in top3 if d in targets]
    res = {
        "loose": 1 if hit else 0,
        "strict": 1 if primary in top3 else 0,
        "mrr": 0.0,
        "neg": sum(1 for d in top3 if d in negs),
        "cov": (len(set(top3) & set(targets)) / len(targets)) if targets else 0.0,
        "neg_before": 0,
    }
    if primary in top3:
        res["mrr"] = 1.0 / (top3.index(primary) + 1)
    # 「无效文档排在有效文档之前」
    valid_ranks = [i for i, d in enumerate(top3) if d in targets]
    neg_ranks = [i for i, d in enumerate(top3) if d in negs]
    if valid_ranks and neg_ranks and min(neg_ranks) < max(valid_ranks):
        res["neg_before"] = 1
    if union_ids is not None:
        res["union_recall"] = 1 if (set(union_ids) & set(targets)) else 0
        res["union_full"] = 1 if targets and set(targets) <= set(union_ids) else 0
        res["union_neg"] = sum(1 for d in union_ids if d in negs)
    return res


def summarize(rows: list[dict]) -> dict:
    n = len(rows)

    def avg(k):
        return round(sum(r.get(k, 0) for r in rows) / n, 4)

    return {
        "n": n,
        "loose@k": avg("loose"),
        "strict@k": avg("strict"),
        "mrr": avg("mrr"),
        "cov@k": avg("cov"),
        "neg@k": sum(r.get("neg", 0) for r in rows),
        "neg_before": sum(r.get("neg_before", 0) for r in rows),
        "union_recall": avg("union_recall"),
        "union_full": avg("union_full"),
        "union_neg": sum(r.get("union_neg", 0) for r in rows),
        "avg_final_count": round(sum(r.get("final_count", 0) for r in rows) / n, 2),
    }


def evaluate(pipeline, dataset: dict, *, final_top_k: int = 3, verbose: bool = False, **run_kwargs):
    """跑全量数据集，返回 (summary, rows)。rows 里带每条 query 的明细便于定位。"""
    rows = []
    t0 = time.time()
    for item in dataset["items"]:
        q = item["query"]
        res = pipeline.run(q, final_top_k=final_top_k, **run_kwargs)
        stage_map = {s["name"]: s for s in res["stages"]}
        final_ids = list(res["final"]["doc_ids"])
        union_ids = None
        if "rrf" in stage_map:
            union_ids = [r["doc_id"] for r in stage_map["rrf"]["results"]]
        elif "dense" in stage_map and "bm25" in stage_map:
            union_ids = [r["doc_id"] for r in stage_map["dense"]["results"]] + \
                        [r["doc_id"] for r in stage_map["bm25"]["results"]]
        row = score_query(item, None, final_ids, union_ids)
        row["final_count"] = len(final_ids)
        row["query"] = q[:40]
        row["targets"] = item.get("target_doc_ids")
        row["primary"] = item.get("primary_target")
        row["top3"] = final_ids
        if "dense" in stage_map:
            row["dense_ids"] = [r["doc_id"] for r in stage_map["dense"]["results"]]
        if "bm25" in stage_map:
            row["bm25_ids"] = [r["doc_id"] for r in stage_map["bm25"]["results"]]
        rows.append(row)
        if verbose:
            mark = "OK " if row["loose"] else "MISS"
            print(f"  [{mark}] strict={row['strict']} neg={row['neg']} n={row['final_count']} {row['query']}")
    summary = summarize(rows)
    summary["seconds"] = round(time.time() - t0, 1)
    return summary, rows


def fmt(summary: dict) -> str:
    return (
        f"loose@k={summary['loose@k']:.3f} strict@k={summary['strict@k']:.3f} "
        f"mrr={summary['mrr']:.3f} cov={summary['cov@k']:.3f} "
        f"neg@k={summary['neg@k']} neg_before={summary['neg_before']} "
        f"unionR={summary['union_recall']:.3f} unionFull={summary['union_full']:.3f} "
        f"unionNeg={summary['union_neg']} cnt={summary['avg_final_count']}"
    )
