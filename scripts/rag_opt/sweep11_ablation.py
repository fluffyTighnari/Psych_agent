"""扫描 11：最终候选配置确认（dense_qmix 固定为 raw1+sq0.5）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

pre = load()
FINAL = dict(DEFAULT_CFG, bm25_spec="rich_b40", dense_doc="problem_solution",
             dense_qmix={"raw": 1.0, "sq": 0.5},
             fusion="wrrf", rrf_k=3, w_dense=1.0, w_bm25=2.0, raw_top_k=15,
             rerank_var="legacy", rerank_mode="blend", blend_alpha=0.3,
             rerank_pool=10, threshold=None)
print("rerank variants:", list(pre.get("rerank", {})))

PROFILES = {
    "raw1 kw1 topic1": {"raw": 1.0, "kw": 1.0, "topic": 1.0},
    "raw1 kw0.5 topic1": {"raw": 1.0, "kw": 0.5, "topic": 1.0},
    "raw1 kw0.5 topic2": {"raw": 1.0, "kw": 0.5, "topic": 2.0},
    "raw1 kw0.5 topic1 dist1": {"raw": 1.0, "kw": 0.5, "topic": 1.0, "distinct": 1.0},
    "raw1 kw0.5 topic1 sq1": {"raw": 1.0, "kw": 0.5, "topic": 1.0, "sq": 1.0},
    "raw1 kw0.5 topic2 dist1": {"raw": 1.0, "kw": 0.5, "topic": 2.0, "distinct": 1.0},
}
print("\n===== A. BM25 查询权重（dense=raw1+sq0.5, blend a=0.3）=====")
best = []
for name, p in PROFILES.items():
    s, _ = summarize(pre, dict(FINAL, bm25_profile=p))
    best.append((name, s))
    print(f"  {fmt(s)}  {name}")

print("\n===== B. 逐项消融（相对最终配置）=====")
BASE_P = PROFILES["raw1 kw0.5 topic1"]
abla = [
    ("最终配置", dict(FINAL, bm25_profile=BASE_P)),
    ("关闭重排(blend)", dict(FINAL, bm25_profile=BASE_P, rerank_var=None)),
    ("重排=纯排序 sort", dict(FINAL, bm25_profile=BASE_P, rerank_mode="sort")),
    ("重排=闸门 filter th=0.02", dict(FINAL, bm25_profile=BASE_P, rerank_mode="filter", threshold=0.02)),
    ("重排=闸门 filter th=0.08", dict(FINAL, bm25_profile=BASE_P, rerank_mode="filter", threshold=0.08)),
    ("RRF k=60（旧默认）", dict(FINAL, bm25_profile=BASE_P, rrf_k=60)),
    ("w_bm25=1.0（等权）", dict(FINAL, bm25_profile=BASE_P, w_bm25=1.0)),
    ("raw_top_k=6（旧默认）", dict(FINAL, bm25_profile=BASE_P, raw_top_k=6)),
    ("dense 只用 search_query 拼接", dict(FINAL, bm25_profile=BASE_P, dense_qmix={"raw_sq": 1.0})),
    ("BM25 索引退回 legacy", dict(FINAL, bm25_profile=BASE_P, bm25_spec="legacy")),
    ("BM25 索引只用构造产物", dict(FINAL, bm25_profile=BASE_P, bm25_spec="construct_only_b40")),
    ("BM25 索引只用原文", dict(FINAL, bm25_profile=BASE_P, bm25_spec="raw_only_b40")),
    ("dense 文档规格 legacy", dict(FINAL, bm25_profile=BASE_P, dense_doc="legacy")),
]
for name, cfg in abla:
    s, _ = summarize(pre, cfg)
    print(f"  {fmt(s)}  {name}")
