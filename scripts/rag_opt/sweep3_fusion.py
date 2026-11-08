"""扫描 3：融合策略细化 —— 加权 RRF / 三链路 RRF(k=小值) / HyDE 独立通道。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

pre = load()
BASE = dict(DEFAULT_CFG, rerank_var=None, threshold=None)
BM = {"bm25_spec": "rich_b40", "bm25_profile": {"raw": 1.0, "topic": 1.0, "kw": 1.0}}
DQ = {"raw": 1.0, "sq": 0.5}
DV = "problem_solution"


def show(title, rows, top=15):
    print(f"\n===== {title} =====")
    for tag, s in sorted(rows, key=lambda x: (-x[1]["loose@k"], -x[1]["strict@k"], x[1]["neg_before"], x[1]["neg@k"]))[:top]:
        print(f"  {fmt(s)}  {tag}")


# A. rrf_k 细扫（rf 默认权重）
rows = []
for rk in [1, 2, 3, 5, 8, 12, 20, 40, 60]:
    for k in [10, 15, 20, 31]:
        s, _ = summarize(pre, dict(BASE, **BM, dense_doc=DV, dense_qmix=DQ, fusion="rrf",
                                   rrf_k=rk, raw_top_k=k))
        rows.append((f"rrf k={rk:3d} raw_top_k={k:2d}", s))
show("A. 纯 RRF：k × raw_top_k", rows, top=20)

# B. 加权 RRF（BM25 更强 → 提高其权重）
rows = []
for wb in [0.5, 1.0, 1.5, 2.0, 3.0]:
    for rk in [1, 3, 5, 10, 20]:
        s, _ = summarize(pre, dict(BASE, **BM, dense_doc=DV, dense_qmix=DQ, fusion="wrrf",
                                   w_dense=1.0, w_bm25=wb, rrf_k=rk, raw_top_k=15))
        rows.append((f"wrrf w_bm25={wb} k={rk:3d}", s))
show("B. 加权 RRF（raw_top_k=15）", rows, top=20)

# C. 三链路：dense + HyDE dense + bm25
rows = []
for rk in [1, 3, 5, 10]:
    for wh in [0.5, 1.0]:
        s, _ = summarize(pre, dict(BASE, **BM, dense_doc=DV, dense_qmix=DQ, fusion="rrf3",
                                   rrf_k=rk, raw_top_k=15, w_hyde=wh))
        rows.append((f"rrf3 k={rk:3d} w_hyde={wh}", s))
show("C. 三链路 RRF（HyDE 独立通道）", rows, top=12)

# D. 同配置下：rrf 有没有用？对比 dense-only / bm25-only / rrf(60) / rrf(1)
print("\n===== D. RRF 增益对照（raw_top_k=15）=====")
for tag, cfg in [
    ("dense only       ", dict(BASE, **BM, dense_doc=DV, dense_qmix=DQ, fusion="dense", raw_top_k=15)),
    ("bm25 only        ", dict(BASE, **BM, dense_doc=DV, dense_qmix=DQ, fusion="bm25", raw_top_k=15)),
    ("rrf k=60 (旧默认)", dict(BASE, **BM, dense_doc=DV, dense_qmix=DQ, fusion="rrf", rrf_k=60, raw_top_k=15)),
    ("rrf k=1          ", dict(BASE, **BM, dense_doc=DV, dense_qmix=DQ, fusion="rrf", rrf_k=1, raw_top_k=15)),
]:
    s, _ = summarize(pre, cfg)
    print(f"  {fmt(s)}  {tag}")
