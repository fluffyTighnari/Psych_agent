"""扫描 5：最终融合配置下的 BM25 查询权重 / 词项组合消融。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

pre = load()
BASE = dict(DEFAULT_CFG, rerank_var=None, threshold=None, fusion="wrrf", rrf_k=3,
            w_dense=1.0, w_bm25=2.0, raw_top_k=15, dense_doc="problem_solution",
            dense_qmix={"raw": 1.0, "sq": 0.5})

PROFILES = {
    "v1(raw+topic+kw)": {"raw": 1, "topic": 1, "kw": 1},
    "raw1+dist3+topic1+kw1": {"raw": 1, "distinct": 3, "topic": 1, "kw": 1},
    "raw1+dist3+topic0.5+kw1": {"raw": 1, "distinct": 3, "topic": 0.5, "kw": 1},
    "raw1+dist2+topic0.5+kw0.5": {"raw": 1, "distinct": 2, "topic": 0.5, "kw": 0.5},
    "raw2+dist3+sq1+kw1+t0.5": {"raw": 2, "distinct": 3, "sq": 1, "kw": 1, "topic": 0.5},
    "raw2+dist3+sq1+kw1+t1": {"raw": 2, "distinct": 3, "sq": 1, "kw": 1, "topic": 1},
    "raw2+dist4+sq1+kw0.5+t0.5": {"raw": 2, "distinct": 4, "sq": 1, "kw": 0.5, "topic": 0.5},
    "raw1+dist1+t1+kw1": {"raw": 1, "distinct": 1, "topic": 1, "kw": 1},
    "raw1+sq1+kw1+t1 (无distinct)": {"raw": 1, "sq": 1, "kw": 1, "topic": 1},
}

print("===== A. 融合配置固定，BM25 查询权重消融（无 rerank）=====")
rows = []
for name, p in PROFILES.items():
    for spec in ["rich_b20", "rich_b40"]:
        s, _ = summarize(pre, dict(BASE, bm25_spec=spec, bm25_profile=p))
        rows.append((f"{spec:9s} {name}", s))
for tag, s in sorted(rows, key=lambda x: (-x[1]["loose@k"], -x[1]["strict@k"], -x[1]["mrr"], x[1]["neg_before"])):
    print(f"  {fmt(s)}  {tag}")

print("\n===== B. dense 权重 / 是否保留 dense（融合配置固定）=====")
rows = []
for wd in [0.0, 0.25, 0.5, 1.0, 1.5]:
    for wb in [1.0, 2.0, 3.0]:
        s, _ = summarize(pre, dict(BASE, bm25_spec="rich_b40", bm25_profile=PROFILES["v1(raw+topic+kw)"],
                                   w_dense=wd, w_bm25=wb))
        rows.append((f"w_dense={wd} w_bm25={wb}", s))
for tag, s in sorted(rows, key=lambda x: (-x[1]["loose@k"], -x[1]["strict@k"], -x[1]["mrr"], x[1]["neg_before"])):
    print(f"  {fmt(s)}  {tag}")
