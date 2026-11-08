"""扫描 4：加入 cross-encoder 重排后的完整配置搜索（依赖 precomp.pkl 的 rerank 矩阵）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import CACHE_DIR  # noqa
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

pre = load()
BM = {"bm25_spec": "rich_b40", "bm25_profile": {"raw": 1.0, "kw": 1.0, "topic": 1.0}}
DV, DQ = "problem_solution", {"raw": 1.0, "sq": 0.5}
NO_RR = dict(DEFAULT_CFG, **BM, dense_doc=DV, dense_qmix=DQ, rerank_var=None, threshold=None)
FUSED = dict(NO_RR, fusion="wrrf", rrf_k=3, w_dense=1.0, w_bm25=2.0, raw_top_k=15)
RVS = list(pre.get("rerank", {}))


def show(title, rows, top=20, key=None):
    print(f"\n===== {title} =====")
    key = key or (lambda s: (-s["loose@k"], -s["strict@k"], -s["mrr"], s["neg_before"], s["neg@k"]))
    for tag, s in sorted(rows, key=lambda x: key(x[1]))[:top]:
        print(f"  {fmt(s)}  {tag}")


print("rerank variants available:", RVS)

rows = []
for rv in RVS:
    for th in [None, 0.0, 0.005, 0.01, 0.02, 0.05, 0.08, 0.15, 0.3]:
        s, _ = summarize(pre, dict(FUSED, rerank_var=rv, threshold=th, rerank_pool=0))
        rows.append((f"rerank={rv:18s} th={th}", s))
show("A. 阈值扫描（重排全量候选池）", rows, top=24)

rows = []
for rv in RVS:
    for pool in [0, 5, 8, 10, 15, 20]:
        for th in [None, 0.02, 0.08]:
            s, _ = summarize(pre, dict(FUSED, rerank_var=rv, threshold=th, rerank_pool=pool))
            rows.append((f"rerank={rv:18s} pool={pool:2d} th={th}", s))
show("B. 候选池 × 阈值", rows, top=24)

rows = []
for spec in ["rich_b20", "rich_b40", "rich_b60"]:
    for rv in RVS:
        for th in [None, 0.02, 0.08]:
            s, _ = summarize(pre, dict(FUSED, bm25_spec=spec, rerank_var=rv, threshold=th, rerank_pool=10))
            rows.append((f"spec={spec:9s} rerank={rv:18s} th={th}", s))
show("C. 索引规格 × 重排（pool=10）", rows, top=20)

print("\n===== D. 对照：开/关重排 =====")
for tag, cfg in [
    ("无重排（融合直出）", dict(FUSED, rerank_var=None)),
    ("重排 pool=0（全量候选）", dict(FUSED, rerank_var=RVS[0], threshold=0.08, rerank_pool=0)),
    ("重排 pool=10", dict(FUSED, rerank_var=RVS[0], threshold=0.08, rerank_pool=10)),
    ("重排 pool=10 无阈值", dict(FUSED, rerank_var=RVS[0], threshold=None, rerank_pool=10)),
]:
    s, _ = summarize(pre, cfg)
    print(f"  {fmt(s)}  {tag}")
