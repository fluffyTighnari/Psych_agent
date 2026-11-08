"""扫描 8：重排的三种用法对比 —— 排序(sort) / 仅作置信闸门(filter) / 分数融合(blend)。"""
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
             rerank_var=None, threshold=None)
RVS = list(pre.get("rerank", {}))


def show(title, rows, top=20):
    print(f"\n===== {title} =====")
    for tag, s in sorted(rows, key=lambda x: (-x[1]["loose@k"], -x[1]["strict@k"], x[1]["neg_before"],
                                              -x[1]["mrr"], x[1]["neg@k"]))[:top]:
        print(f"  {fmt(s)}  {tag}")


s, _ = summarize(pre, FUSED)
print(f"基线（完全不重排）: {fmt(s)}")

rows = []
for rv in RVS:
    for pool in [5, 8, 10, 15]:
        for th in [None, 0.005, 0.02, 0.05, 0.08]:
            s, _ = summarize(pre, dict(FUSED, rerank_var=rv, rerank_mode="filter",
                                       rerank_pool=pool, threshold=th))
            rows.append((f"filter rv={rv} pool={pool:2d} th={th}", s))
show("A. rerank 仅作置信闸门（保持融合排名）", rows, top=22)

rows = []
for rv in RVS:
    for alpha in [0.1, 0.3, 0.5, 1.0, 2.0]:
        for pool in [10, 15]:
            s, _ = summarize(pre, dict(FUSED, rerank_var=rv, rerank_mode="blend",
                                       blend_alpha=alpha, rerank_pool=pool, threshold=None))
            rows.append((f"blend rv={rv} alpha={alpha} pool={pool}", s))
show("B. 融合排名分 + alpha×重排分", rows, top=22)

rows = []
for rv in RVS:
    for pool in [5, 8, 10]:
        s, _ = summarize(pre, dict(FUSED, rerank_var=rv, rerank_mode="sort",
                                   rerank_pool=pool, threshold=None))
        rows.append((f"sort rv={rv} pool={pool}", s))
show("C. 纯重排排序（对照）", rows, top=10)
