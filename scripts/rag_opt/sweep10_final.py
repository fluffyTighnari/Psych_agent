"""扫描 10：最终 blend 配置下的 BM25 查询权重 / dense 混合权重复核。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

pre = load()
FINAL = dict(DEFAULT_CFG, bm25_spec="rich_b40", dense_doc="problem_solution",
             fusion="wrrf", rrf_k=3, w_dense=1.0, w_bm25=2.0, raw_top_k=15,
             rerank_var="legacy", rerank_mode="blend", blend_alpha=0.3,
             rerank_pool=10, threshold=None)

PROFILES = {
    "raw1 kw1 topic1 (v1 原样)": {"raw": 1.0, "kw": 1.0, "topic": 1.0},
    "raw1 kw0.5 topic1": {"raw": 1.0, "kw": 0.5, "topic": 1.0},
    "raw1 kw0.5 topic2": {"raw": 1.0, "kw": 0.5, "topic": 2.0},
    "raw1 kw1 topic2": {"raw": 1.0, "kw": 1.0, "topic": 2.0},
    "raw1 kw0.5 topic1 +sq1": {"raw": 1.0, "kw": 0.5, "topic": 1.0, "sq": 1.0},
    "raw1 kw0.5 topic1 +dist1": {"raw": 1.0, "kw": 0.5, "topic": 1.0, "distinct": 1.0},
    "raw1 kw0.5 topic1 +sq1+dist1": {"raw": 1.0, "kw": 0.5, "topic": 1.0, "sq": 1.0, "distinct": 1.0},
}
print("===== A. BM25 查询权重（blend 最终配置）=====")
for name, p in PROFILES.items():
    s, _ = summarize(pre, dict(FINAL, bm25_profile=p))
    print(f"  {fmt(s)}  {name}")

print("\n===== B. dense 查询混合（blend 最终配置）=====")
for name, mix in {
    "raw only": {"raw": 1.0},
    "raw1 sq0.5": {"raw": 1.0, "sq": 0.5},
    "raw1 sq1": {"raw": 1.0, "sq": 1.0},
    "raw_sq 拼接": {"raw_sq": 1.0},
    "raw1 sq0.5 +he0.3": {"raw": 1.0, "sq": 0.5, "hyde_experience": 0.3},
    "raw1 sq0.5 +hp0.3": {"raw": 1.0, "sq": 0.5, "hyde_principle": 0.3},
    "raw1 sq0.5 +he0.3+hp0.3": {"raw": 1.0, "sq": 0.5, "hyde_experience": 0.3, "hyde_principle": 0.3},
}.items():
    s, _ = summarize(pre, dict(FINAL, bm25_profile=PROFILES["raw1 kw1 topic1 (v1 原样)"], dense_qmix=mix))
    print(f"  {fmt(s)}  {name}")

print("\n===== C. dense 文档规格（blend 最终配置）=====")
for dv in ["legacy", "title_summary_kw", "problem_solution", "rich", "full"]:
    s, _ = summarize(pre, dict(FINAL, bm25_profile=PROFILES["raw1 kw1 topic1 (v1 原样)"], dense_doc=dv))
    print(f"  {fmt(s)}  {dv}")
