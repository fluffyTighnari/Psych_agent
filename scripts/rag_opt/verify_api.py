"""接口冒烟验证：/retrieval/meta + /retrieval/debug 的默认与关键开关。

用法：python scripts/rag_opt/verify_api.py [base_url]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import load_dataset  # noqa

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001").rstrip("/")


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))


ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


meta = get("/retrieval/meta")
d = meta["data"]
check("meta.code=200", meta["code"] == 200)
check("meta 默认参数已更新", d["defaults"]["rrf_k"] == 3 and d["defaults"]["raw_top_k"] == 15
      and d["defaults"]["rerank_mode"] == "blend", json.dumps(d["defaults"], ensure_ascii=False))
check("meta 暴露富索引规格", d["index_spec"]["bm25_mode"] == "rich"
      and abs(d["index_spec"]["bm25_b"] - 0.4) < 1e-6,
      json.dumps(d["index_spec"].get("bm25_mode")))
check("meta 阶段含 hyde", any(s["name"] == "hyde" for s in d["stages"]))
check("vector_count == doc_count", d["vector_count"] == d["doc_count"],
      f"{d['vector_count']}/{d['doc_count']}")

ds = load_dataset()["items"]
q = ds[0]["query"]

t0 = time.time()
r = post("/retrieval/debug", {"query": q, "final_top_k": 3})
dt = time.time() - t0
data = r["data"]
check("debug.code=200", r["code"] == 200)
check("阶段顺序固定", [s["name"] for s in data["stages"]] ==
      ["optimize_prompt", "dense", "bm25", "rrf", "rerank"], str([s["name"] for s in data["stages"]]))
check("final 条数 == final_top_k", data["final"]["count"] == 3, f"count={data['final']['count']}")
check("optimized 含 v2 字段", "distinctive_terms" in data["optimized"]
      and "hyde_experience" in data["optimized"], json.dumps(data["optimized"], ensure_ascii=False)[:180])
check("params 回显新参数", data["params"]["rerank_mode"] == "blend"
      and data["params"]["blend_alpha"] == 0.3, json.dumps(data["params"], ensure_ascii=False))
check("目标文档命中且排第 1", data["final"]["doc_ids"][0] == ds[0]["primary_target"],
      f"got={data['final']['doc_ids'][:1]} want={ds[0]['primary_target']}")
print(f"     latency_ms={data['latency_ms']} wall={dt:.1f}s")

# 生产 v1 行为复现：rerank_mode=sort + 0.08 阈值
r2 = post("/retrieval/debug", {"query": q, "final_top_k": 3, "rerank_mode": "sort", "score_threshold": 0.08})
check("sort 模式可切换", r2["data"]["params"]["rerank_mode"] == "sort"
      and r2["data"]["final"]["count"] <= 3, f"count={r2['data']['final']['count']}")

# filter 模式：只做闸门，final 必须仍截断到 final_top_k
r3 = post("/retrieval/debug", {"query": q, "final_top_k": 3, "rerank_mode": "filter", "score_threshold": 0.02})
check("filter 模式 final 仍截断到 final_top_k", r3["data"]["final"]["count"] <= 3,
      f"count={r3['data']['final']['count']}")

# HyDE 链路可开启
r4 = post("/retrieval/debug", {"query": q, "final_top_k": 3, "use_hyde": True})
check("use_hyde 触发 hyde 阶段", any(s["name"] == "hyde" for s in r4["data"]["stages"]),
      str([s["name"] for s in r4["data"]["stages"]]))

# 参数校验
r5 = post("/retrieval/debug", {"query": q, "rerank_mode": "bogus"})
check("非法 rerank_mode → 400", r5["code"] == 400, str(r5.get("msg")))
r6 = post("/retrieval/debug", {"query": q, "blend_alpha": 99})
check("非法 blend_alpha → 400", r6["code"] == 400, str(r6.get("msg")))
r7 = post("/retrieval/debug", {"query": "   "})
check("空 query → 400", r7["code"] == 400, str(r7.get("msg")))

print("\n结果:", "ALL PASS" if ok else "存在 FAIL")
sys.exit(0 if ok else 1)
