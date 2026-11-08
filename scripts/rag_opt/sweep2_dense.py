"""扫描 2：dense 文档/查询规格、HyDE、以及双路融合（仍不依赖 rerank）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

pre = load()
BASE = dict(DEFAULT_CFG, rerank_var=None, threshold=None)
BM = {"bm25_spec": "rich_b40", "bm25_profile": {"raw": 1.0, "topic": 1.0, "kw": 1.0}}


def line(tag, s):
    print(f"  {fmt(s)}  {tag}")


print("===== A. dense 文档规格 × 查询规格（fusion=dense, top3）=====")
res = []
for dv in ["legacy", "title_summary_kw", "problem_solution", "rich", "full"]:
    for qk in ["raw", "sq", "raw_sq", "raw_sq_kw", "instruct_raw_sq", "instruct_raw"]:
        s, _ = summarize(pre, dict(BASE, **BM, dense_doc=dv, dense_qmix={qk: 1.0}, fusion="dense"))
        res.append(((dv, qk), s))
for k, s in sorted(res, key=lambda x: (-x[1]["loose@k"], x[1]["neg@k"]))[:14]:
    line(f"doc={k[0]:18s} q={k[1]}", s)

print("\n===== B. HyDE 混合（doc=problem_solution, fusion=dense）=====")
mixes = {
    "raw_sq": {"raw_sq": 1.0},
    "raw1+sq0.5": {"raw": 1.0, "sq": 0.5},
    "raw1+sq0.5+he1": {"raw": 1.0, "sq": 0.5, "hyde_experience": 1.0},
    "raw1+sq0.5+hp1": {"raw": 1.0, "sq": 0.5, "hyde_principle": 1.0},
    "raw1+sq0.5+he1+hp1": {"raw": 1.0, "sq": 0.5, "hyde_experience": 1.0, "hyde_principle": 1.0},
    "raw1+he1+hp1": {"raw": 1.0, "hyde_experience": 1.0, "hyde_principle": 1.0},
    "he+hp": {"hyde_experience": 1.0, "hyde_principle": 1.0},
    "he_only": {"hyde_experience": 1.0},
    "hp_only": {"hyde_principle": 1.0},
    "raw1+sq0.5+he0.5+hp0.5": {"raw": 1.0, "sq": 0.5, "hyde_experience": 0.5, "hyde_principle": 0.5},
    "raw2+sq1+he1+hp1": {"raw": 2.0, "sq": 1.0, "hyde_experience": 1.0, "hyde_principle": 1.0},
}
for name, mix in mixes.items():
    s, _ = summarize(pre, dict(BASE, **BM, dense_doc="problem_solution", dense_qmix=mix, fusion="dense"))
    line(name, s)

print("\n===== C. 双路融合（rich BM25 + best dense mix）=====")
for fusion in ["dense", "bm25", "union", "rrf"]:
    for rk in ([60] if fusion != "rrf" else [1, 5, 10, 20, 60, 200]):
        for k in [6, 10, 15]:
            s, _ = summarize(pre, dict(BASE, **BM, dense_doc="problem_solution",
                                      dense_qmix={"raw": 1.0, "sq": 0.5},
                                      fusion=fusion, rrf_k=rk, raw_top_k=k))
            line(f"fusion={fusion:5s} rrf_k={rk:3d} raw_top_k={k:2d}", s)
