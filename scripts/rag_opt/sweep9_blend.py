"""扫描 9：blend 系数 alpha 精细化 + 稳健性检查（不同索引规格 / 召回规模）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

pre = load()
FUSED = dict(DEFAULT_CFG, bm25_spec="rich_b40",
             bm25_profile={"raw": 1.0, "kw": 1.0, "topic": 1.0},
             dense_doc="problem_solution", dense_qmix={"raw": 1.0, "sq": 0.5},
             fusion="wrrf", rrf_k=3, w_dense=1.0, w_bm25=2.0, raw_top_k=15,
             rerank_var="legacy", rerank_mode="blend", threshold=None)
RVS = list(pre.get("rerank", {}))
print("variants:", RVS)

print("\n===== A. alpha × pool（rv=legacy）=====")
rows = []
for alpha in [0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.7, 1.0]:
    for pool in [5, 8, 10, 12, 15, 0]:
        s, _ = summarize(pre, dict(FUSED, blend_alpha=alpha, rerank_pool=pool))
        rows.append((f"alpha={alpha} pool={pool}", s))
for tag, s in sorted(rows, key=lambda x: (-x[1]["mrr"], x[1]["neg_before"], x[1]["neg@k"], -x[1]["cov@k"]))[:20]:
    print(f"  {fmt(s)}  {tag}")

print("\n===== B. 稳健性：不同索引规格 × alpha（pool=10）=====")
for spec in ["rich_b20", "rich_b40", "rich_b60", "rich_b75"]:
    line = []
    for alpha in [0.0, 0.2, 0.3, 0.5]:
        s, _ = summarize(pre, dict(FUSED, bm25_spec=spec, blend_alpha=alpha, rerank_pool=10))
        line.append(f"a={alpha}: mrr={s['mrr']:.3f} negb={s['neg_before']} neg={s['neg@k']} loose={s['loose@k']:.3f}")
    print(f"  {spec:9s} " + " | ".join(line))

print("\n===== C. 稳健性：raw_top_k × alpha（spec=rich_b40, pool=10）=====")
for k in [6, 8, 10, 15, 20, 31]:
    line = []
    for alpha in [0.0, 0.3, 0.5]:
        s, _ = summarize(pre, dict(FUSED, raw_top_k=k, blend_alpha=alpha, rerank_pool=10))
        line.append(f"a={alpha}: mrr={s['mrr']:.3f} negb={s['neg_before']} neg={s['neg@k']} loose={s['loose@k']:.3f} strict={s['strict@k']:.3f}")
    print(f"  raw_top_k={k:2d} " + " | ".join(line))

print("\n===== D. 稳健性：rrf_k / 权重 × alpha=0.3 =====")
for rk in [1, 3, 5, 10, 60]:
    for wb in [1.0, 2.0]:
        s, _ = summarize(pre, dict(FUSED, rrf_k=rk, w_bm25=wb, blend_alpha=0.3, rerank_pool=10))
        print(f"  rrf_k={rk:3d} w_bm25={wb}  {fmt(s)}")
