"""通过 HTTP 调用 /api/retrieval/debug 跑全量数据集（端到端验证检索接口本身）。

用法：python scripts/rag_opt/eval_via_api.py [base_url]
默认 http://127.0.0.1:8001
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import CACHE_DIR, load_dataset  # noqa

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
URL = BASE.rstrip("/") + "/retrieval/debug"

dataset = load_dataset()


def call(payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run(label: str, extra: dict | None = None) -> dict:
    agg = dict(loose=0, strict=0, mrr=0.0, cov=0.0, neg=0, neg_before=0, cnt=0)
    rows = []
    t0 = time.time()
    for it in dataset["items"]:
        payload = {"query": it["query"], "final_top_k": 3}
        payload.update(extra or {})
        r = call(payload)
        if r.get("code") != 200:
            print("  API ERROR:", r.get("msg"))
            continue
        d = r["data"]
        top = list(d["final"]["doc_ids"])
        tgt = set(it["target_doc_ids"])
        negs = set(it["hard_negatives"])
        prim = it["primary_target"]
        hit = [x for x in top if x in tgt]
        agg["loose"] += 1 if hit else 0
        agg["strict"] += 1 if prim in top else 0
        agg["mrr"] += (1.0 / (top.index(prim) + 1)) if prim in top else 0.0
        agg["cov"] += (len(set(top) & tgt) / len(tgt)) if tgt else 0.0
        agg["neg"] += sum(1 for x in top if x in negs)
        agg["cnt"] += len(top)
        vr = [i for i, x in enumerate(top) if x in tgt]
        nr = [i for i, x in enumerate(top) if x in negs]
        if vr and nr and min(nr) < max(vr):
            agg["neg_before"] += 1
        rows.append({"q": it["query"][:24], "top": top, "loose": bool(hit)})
    n = len(dataset["items"])
    s = {k: (round(v / n, 4) if isinstance(v, float) else v) for k, v in agg.items()}
    s["avg_cnt"] = round(agg["cnt"] / n, 2)
    s["seconds"] = round(time.time() - t0, 1)
    print(f"{label:34s} loose@3={s['loose']/n:.3f} strict@3={s['strict']/n:.3f} mrr={s['mrr']:.3f} "
          f"cov@3={s['cov']:.3f} neg@3={s['neg']} neg_before={s['neg_before']} cnt={s['avg_cnt']} "
          f"({s['seconds']}s)")
    return s


if __name__ == "__main__":
    out = {}
    out["优化后默认（API 默认参数）"] = run("优化后默认（API 默认参数）")
    out["消融：rerank_mode=sort th=0.08"] = run(
        "消融：rerank_mode=sort th=0.08", {"rerank_mode": "sort", "score_threshold": 0.08})
    out["消融：关闭重排"] = run("消融：关闭重排", {"rerank": False})
    out["消融：filter th=0.02"] = run("消融：filter th=0.02",
                                      {"rerank_mode": "filter", "score_threshold": 0.02})
    json.dump(out, open(CACHE_DIR / "api_eval.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("saved ->", CACHE_DIR / "api_eval.json")
