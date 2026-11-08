"""短 query（域外分布）健全性抽查：对比优化配置与 v1 行为的返回结果。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.helper.knowledge_cache import KNOWLEDGE_CACHE  # noqa
from core.helper.retrieval_pipeline import RetrievalPipeline, get_retrieval_components  # noqa

comps = get_retrieval_components()
pipe = RetrievalPipeline(**comps)
title = {d.doc_id: (d.title or d.summary[:24]) for d in KNOWLEDGE_CACHE.documents}

QUERIES = [
    "我最近总是内耗，怎么和自己和解",
    "怎么才能不拖延",
    "社恐怎么办",
    "和父母关系不好很痛苦",
    "总是和别人比较，很焦虑",
    "我不知道自己想要什么",
]

for q in QUERIES:
    print(f"\nQ: {q}")
    for label, kw in [("优化默认", {}), ("v1 重排方式", dict(rerank_mode="sort", score_threshold=0.08)),
                      ("无重排", dict(rerank=False))]:
        r = pipe.run(q, final_top_k=3, **kw)
        ids = r["final"]["doc_ids"]
        print(f"  {label:10s} " + " | ".join(f"{title.get(i,'?')[:18]}" for i in ids))
