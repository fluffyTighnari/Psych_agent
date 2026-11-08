"""分析最终 rows：哪些 query 的 target 没进 top-3、哪些 hard negative 进了。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import CACHE_DIR, load_dataset  # noqa

rows = json.load(open(CACHE_DIR / "final_rows.json", encoding="utf-8"))
items = load_dataset()["items"]
by_primary = {i["primary_target"]: i for i in items}

miss = 0
for r in rows:
    it = by_primary.get(r["primary"])
    tgt = list(it["target_doc_ids"])
    negs = list(it["hard_negatives"])
    top = r["top3"]
    got = [d for d in top if d in tgt]
    lost = [d for d in tgt if d not in top]
    negin = [d for d in top if d in negs]
    flag = "OK " if not lost else ("PART" if got else "MISS")
    if lost:
        miss += 1
    print(f"{flag} cov={r['cov']:.2f} top3={[d[:6] for d in top]} lost={[d[:6] for d in lost]} "
          f"neg={[d[:6] for d in negin]} | {it['query'][:24]}")
print(f"\n有 target 漏检的 query 数: {miss}/{len(rows)}")
