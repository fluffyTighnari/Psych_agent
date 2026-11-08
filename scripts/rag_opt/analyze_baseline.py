"""分析 baseline rows：哪条 miss、无效文档在哪、各阶段 top-k 覆盖情况。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import load_dataset  # noqa

rows = json.load(open("scripts/rag_opt/.cache/baseline_full_rows.json", encoding="utf-8"))
ds = {i["query"]: i for i in load_dataset()["items"]}

n = len(rows)
print(f"n={n}")
print("final_count 分布:", {c: sum(1 for r in rows if r["final_count"] == c) for c in
                            sorted({r["final_count"] for r in rows})})

nmiss = 0
for r in rows:
    item = ds[r["query"] + ""] if r["query"] + "" in ds else None
    # rows 里 query 被截断，用 target 匹配
for r in rows:
    item = next((i for i in load_dataset()["items"] if i["primary_target"] == r["primary"]), None)
    tgt = set(item["target_doc_ids"])
    negs = set(item["hard_negatives"])
    top3 = r["top3"]
    dense = set(r.get("dense_ids") or [])
    bm25 = set(r.get("bm25_ids") or [])
    d_hit = len(dense & tgt)
    b_hit = len(bm25 & tgt)
    f_hit = len(set(top3) & tgt)
    if f_hit == 0:
        nmiss += 1
    print(f"{'MISS' if f_hit==0 else ('part' if f_hit<len(tgt) else 'full')} "
          f"f={r['final_count']} tgt={len(tgt)} | dense_hit={d_hit} bm25_hit={b_hit} "
          f"top3={[d[:8] for d in top3]} neg_in_top={[d[:8] for d in top3 if d in negs]} "
          f"| {item['query'][:28]}")
print("total miss:", nmiss)
