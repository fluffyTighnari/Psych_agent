"""扫描 6：BM25 查询词项相对权重细扫（BM25 分数对整体缩放不变，只需扫相对比例）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

pre = load()
BASE = dict(DEFAULT_CFG, rerank_var=None, threshold=None, fusion="wrrf", rrf_k=3,
            w_dense=1.0, w_bm25=2.0, raw_top_k=15, dense_doc="problem_solution",
            dense_qmix={"raw": 1.0, "sq": 0.5}, bm25_spec="rich_b40")

rows = []
for kw in [0.0, 0.5, 1.0, 2.0]:
    for tp in [0.0, 0.5, 1.0, 2.0]:
        for di in [0.0, 1.0]:
            p = {"raw": 1.0, "kw": kw, "topic": tp, "distinct": di}
            s, _ = summarize(pre, dict(BASE, bm25_profile=p))
            rows.append((f"raw1 kw={kw} topic={tp} distinct={di}", s))
for tag, s in sorted(rows, key=lambda x: (-x[1]["loose@k"], -x[1]["strict@k"], -x[1]["mrr"], x[1]["neg_before"], x[1]["neg@k"]))[:20]:
    print(f"  {fmt(s)}  {tag}")
