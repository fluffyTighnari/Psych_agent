"""基线评测：现有流水线在 rag_optimize 数据集上的表现（多档对比）。"""
from __future__ import annotations

import json
import sys

from harness import CachedOptimizer, evaluate, fmt, load_dataset

from config.prompt_config import optimizer_prompt
from core.helper.retrieval_pipeline import RetrievalPipeline, get_retrieval_components

import hashlib

dataset = load_dataset()
comps = get_retrieval_components()

ver = hashlib.md5(optimizer_prompt.encode("utf-8")).hexdigest()[:10]
opt = CachedOptimizer(comps["prompt_optimizer"], ver, "baseline")
comps["prompt_optimizer"] = opt

pipe = RetrievalPipeline(**comps)

MODES = {
    "full(d+b+rrf+rerank)": dict(dense=True, bm25=True, rrf=True, rerank=True),
    "dense+rerank": dict(dense=True, bm25=False, rrf=False, rerank=True),
    "bm25+rerank": dict(dense=False, bm25=True, rrf=False, rerank=True),
    "dense only": dict(dense=True, bm25=False, rrf=False, rerank=False),
    "bm25 only": dict(dense=False, bm25=True, rrf=False, rerank=False),
    "rrf only(no rerank)": dict(dense=True, bm25=True, rrf=True, rerank=False),
}

out = {}
for name, flags in MODES.items():
    s, rows = evaluate(pipe, dataset, final_top_k=3, **flags)
    out[name] = s
    print(f"{name:26s} {fmt(s)}")
    if name == "full(d+b+rrf+rerank)":
        json.dump(rows, open("scripts/rag_opt/.cache/baseline_full_rows.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

print("\noptimizer cache hits/misses:", opt.hits, opt.misses)
json.dump(out, open("scripts/rag_opt/.cache/baseline_summary.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
