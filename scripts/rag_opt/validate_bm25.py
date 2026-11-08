"""校验 BM25 部分：模拟器 top-k vs 真实 BM25TagIndexer.search() 的精确一致性。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate import bm25_scores, load  # noqa

from core.helper.BM25 import BM25TagIndexer  # noqa
from core.helper.knowledge_cache import KNOWLEDGE_CACHE  # noqa

pre = load()
docs = list(KNOWLEDGE_CACHE.documents)
TMP = Path(__file__).resolve().parent / ".tmp"

for spec in ["legacy", "rich_b20", "rich_b40", "rich_specific_b40", "raw_only_b40"]:
    idx = BM25TagIndexer(documents=docs, bm25_path=str(TMP / f"chk_{spec}.pkl"), **(
        dict(field_weights=None) if spec == "legacy" else {
            "rich_b20": dict(field_weights=dict(topic=3, keyword=2, title=3, summary=2, problem=2, solution=2, analysis=1, content=1), b=0.2),
            "rich_b40": dict(field_weights=dict(topic=3, keyword=2, title=3, summary=2, problem=2, solution=2, analysis=1, content=1), b=0.4),
            "rich_specific_b40": dict(field_weights=dict(topic=1, keyword=4, title=4, summary=2, problem=4, solution=4, analysis=1, content=1), b=0.4),
            "raw_only_b40": dict(field_weights=dict(title=1, problem=1, solution=1, analysis=1, content=1), b=0.4),
        }[spec]))
    bad = 0
    for qi, it in enumerate(pre["items"]):
        # 用索引规格的 vocab id 顺序对齐：模拟器矩阵的行是 union vocab
        vec = bm25_scores(pre, spec, qi, {"raw": 1.0, "topic": 1.0, "kw": 1.0})
        order = np.argsort(-vec)
        sim_ids = [pre["doc_ids"][i] for i in order[:3]]
        # 真实：直接调用 search（与 pipeline 内部完全一致）
        toks = pre["bm25_query"][qi]["raw"] + pre["bm25_query"][qi]["topic"] + pre["bm25_query"][qi]["kw"]
        real_ids = list(idx.search(toks, 3))
        if sim_ids != real_ids:
            bad += 1
            if bad <= 3:
                print(f"  DIFF spec={spec} qi={qi} sim={[d[:8] for d in sim_ids]} real={[d[:8] for d in real_ids]}")
    print(f"{spec:20s} 不一致 {bad}/{len(pre['items'])}")
