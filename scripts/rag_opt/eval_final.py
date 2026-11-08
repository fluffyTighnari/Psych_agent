"""最终端到端验证：用**真实**的 RetrievalPipeline + 重建后的索引跑 rag_optimize 全量数据集。

与离线模拟器不同，这里走的是 api/retrieval_debug 背后的同一条代码路径，
用于确认「优化后的默认配置」在线上接口上真实达到报告中的指标。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import CACHE_DIR, CachedOptimizer, evaluate, fmt, load_dataset  # noqa

from config.prompt_config import optimizer_prompt, optimizer_prompt_lite  # noqa
from core.helper.retrieval_pipeline import RetrievalPipeline, get_retrieval_components  # noqa
from core.helper import retrieval_config as RC  # noqa

dataset = load_dataset()
comps = get_retrieval_components()
ver_lite = hashlib.md5(optimizer_prompt_lite.encode("utf-8")).hexdigest()[:10]
ver_hyde = hashlib.md5(optimizer_prompt.encode("utf-8")).hexdigest()[:10]
opt = CachedOptimizer(comps["prompt_optimizer"], ver_lite, "precomp", hyde_version=ver_hyde)
comps["prompt_optimizer"] = opt
pipe = RetrievalPipeline(**comps)

print(f"prompt_version lite={ver_lite} hyde={ver_hyde}  cache_hits={opt.hits}  misses={opt.misses}")
print(f"bm25 index spec = {getattr(comps['bm25'], 'index_spec', {})}")
print(f"defaults: raw_top_k={RC.DEFAULT_RAW_TOP_K} rrf_k={RC.DEFAULT_RRF_K} "
      f"w=({RC.DEFAULT_W_DENSE},{RC.DEFAULT_W_BM25}) pool={RC.DEFAULT_RERANK_POOL} "
      f"mode={RC.DEFAULT_RERANK_MODE} alpha={RC.DEFAULT_BLEND_ALPHA} th={RC.DEFAULT_SCORE_THRESHOLD}")

RUNS = {
    "优化后默认（全链路）": dict(),
    "消融：关闭重排": dict(rerank=False),
    "消融：重排=v1 sort + th0.08": dict(rerank_mode="sort", score_threshold=0.08),
    "消融：重排=v1 sort 无阈值": dict(rerank_mode="sort", score_threshold=0.0),
    "消融：重排=filter th0.02": dict(rerank_mode="filter", score_threshold=0.02),
    "消融：RRF k=60（v1 默认）": dict(rrf_k=60),
    "消融：raw_top_k=6（v1 默认）": dict(raw_top_k=6),
}

out = {}
for name, kw in RUNS.items():
    s, rows = evaluate(pipe, dataset, final_top_k=3, **kw)
    out[name] = s
    print(f"{name:34s} {fmt(s)}")
    if name.startswith("优化后默认"):
        json.dump(rows, open(CACHE_DIR / "final_rows.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

# 生产入口（retrieve_documents）与 run() 一致性自证：同一条路径，防止装配回归
print("\n===== 生产入口 retrieve_documents 与 run() 一致性 =====")
same = 0
for it in dataset["items"][:8]:
    docs = pipe.retrieve_documents(it["query"], RC.DEFAULT_RAW_TOP_K, 3)
    ids = [d.doc_id for d in docs]
    res = pipe.run(it["query"], final_top_k=3)
    if ids == res["final"]["doc_ids"]:
        same += 1
    else:
        print("  DIFF", ids, res["final"]["doc_ids"])
print(f"  前 8 条中 retrieve_documents 与 run() 一致: {same}/8")

json.dump(out, open(CACHE_DIR / "final_summary.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("\nsummary saved ->", CACHE_DIR / "final_summary.json")
