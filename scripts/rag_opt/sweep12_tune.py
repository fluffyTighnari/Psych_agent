"""扫描 12：收尾微调 —— w_bm25 / rrf_k / blend alpha 联合细扫。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

pre = load()
P = {"raw": 1.0, "kw": 0.5, "topic": 1.0}
BASE = dict(DEFAULT_CFG, bm25_spec="rich_b40", bm25_profile=P, dense_doc="problem_solution",
            dense_qmix={"raw": 1.0, "sq": 0.5}, fusion="wrrf", w_dense=1.0,
            raw_top_k=15, rerank_var="legacy", rerank_mode="blend", rerank_pool=10,
            threshold=None)

rows = []
for rk in [1, 2, 3, 5, 8]:
    for wb in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
        for al in [0.2, 0.3, 0.5]:
            s, _ = summarize(pre, dict(BASE, rrf_k=rk, w_bm25=wb, blend_alpha=al))
            rows.append((f"rrf_k={rk} w_bm25={wb} alpha={al}", s))
print("===== 按 (mrr, cov, -neg, -neg_before) 排序 =====")
for tag, s in sorted(rows, key=lambda x: (-x[1]["mrr"], -x[1]["cov@k"], x[1]["neg@k"], x[1]["neg_before"]))[:24]:
    print(f"  {fmt(s)}  {tag}")

print("\n===== 按 (loose, strict, -neg_before, -neg, mrr) 排序（业务口径优先）=====")
for tag, s in sorted(rows, key=lambda x: (-x[1]["loose@k"], -x[1]["strict@k"], x[1]["neg_before"], x[1]["neg@k"], -x[1]["mrr"]))[:24]:
    print(f"  {fmt(s)}  {tag}")
