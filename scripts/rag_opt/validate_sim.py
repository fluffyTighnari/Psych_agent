"""校验：离线模拟器 vs 真实 pipeline（关闭 rerank，排除 cross-encoder 变量）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate import DEFAULT_CFG, bm25_scores, dense_scores, load, run_one, summarize  # noqa

from scripts.rag_opt.harness import CachedOptimizer  # noqa
from core.helper.retrieval_pipeline import RetrievalPipeline, get_retrieval_components  # noqa

pre = load()
comps = get_retrieval_components()
ver = pre.get("prompt_version", "x")
opt = CachedOptimizer(comps["prompt_optimizer"], ver, "precomp")
comps["prompt_optimizer"] = opt
pipe = RetrievalPipeline(**comps)

cfg = dict(DEFAULT_CFG, rerank_var=None, threshold=None, fusion="rrf", raw_top_k=6,
           bm25_spec="legacy", bm25_profile={"raw": 1.0, "topic": 1.0, "kw": 1.0},
           dense_doc="legacy", dense_qmix={"raw_sq": 1.0})

print("qi | sim top3                          | real top3")
bad = 0
for qi, it in enumerate(pre["items"]):
    sim = run_one(pre, qi, cfg)
    res = pipe.run(it["query"], dense=True, bm25=True, rrf=True, rerank=False, raw_top_k=6, final_top_k=3)
    real = list(res["final"]["doc_ids"])
    same = sim == real
    if not same:
        bad += 1
        print(f"{qi:2d} | {[d[:8] for d in sim]} | {[d[:8] for d in real]}  DIFF")
    if qi >= 5 and bad == 0:
        break

# 全量比对
bad = 0
for qi, it in enumerate(pre["items"]):
    sim = run_one(pre, qi, cfg)
    res = pipe.run(it["query"], dense=True, bm25=True, rrf=True, rerank=False, raw_top_k=6, final_top_k=3)
    real = list(res["final"]["doc_ids"])
    if sim != real:
        bad += 1
        if bad <= 5:
            print(f"DIFF qi={qi}: sim={[d[:8] for d in sim]} real={[d[:8] for d in real]}")
print("全量不一致条数:", bad, "/", len(pre["items"]))

s, _ = summarize(pre, cfg)
print("sim :", s)
