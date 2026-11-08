"""扫描 1：BM25 索引规格 / 查询词项权重 / 召回规模 / 融合方式（不依赖 rerank）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import CACHE_DIR  # noqa
from simulate import DEFAULT_CFG, bm25_scores, dense_scores, fmt, load, summarize  # noqa


def show(title, rows, top=12, key=lambda s: (-s["loose@k"], -s["strict@k"], s["neg@k"])):
    print(f"\n===== {title} =====")
    for cfg, s in sorted(rows, key=lambda x: key(x[1]))[:top]:
        tag = ", ".join(f"{k}={v}" for k, v in cfg.items() if k in CFG_KEYS)
        print(f"  {fmt(s)}  | {tag}")


CFG_KEYS = {"bm25_spec", "bm25_profile", "dense_doc", "dense_qmix", "fusion", "rrf_k",
            "threshold", "raw_top_k", "final_top_k", "rerank_var"}


def main():
    pre = load()
    # 无 rerank 时：先看「召回本身」的上限，再看融合结果
    base = dict(DEFAULT_CFG)
    base["rerank_var"] = None
    base["threshold"] = None

    # ---------- 0. 各索引规格在「同样查询词项」下的召回上限 ----------
    print("===== 0. BM25 索引规格（查询词项固定为 v1: raw+topic+kw，raw_top_k=6）=====")
    v1prof = {"raw": 1.0, "topic": 1.0, "kw": 1.0}
    res = []
    for spec in pre["bm25"]:
        cfg = dict(base, bm25_spec=spec, bm25_profile=v1prof, fusion="bm25")
        s, _ = summarize(pre, cfg)
        res.append((cfg, s))
    for cfg, s in sorted(res, key=lambda x: (-x[1]["loose@k"], -x[1]["strict@k"])):
        print(f"  {fmt(s)}  {cfg['bm25_spec']:20s} avgdl={pre['bm25'][cfg['bm25_spec']]['avgdl']:.0f}")

    # ---------- 1. BM25 查询词项权重（最优索引 + 网格） ----------
    best_spec = max(pre["bm25"], key=lambda sp: summarize(
        pre, dict(base, bm25_spec=sp, bm25_profile=v1prof, fusion="bm25"))[0]["loose@k"])
    print(f"\n===== 1. BM25 查询词项权重（spec={best_spec}）=====")
    profs = {
        "v1(raw+topic+kw)": {"raw": 1, "topic": 1, "kw": 1},
        "raw_only": {"raw": 1},
        "raw2": {"raw": 2},
        "raw2+kw1+t1": {"raw": 2, "kw": 1, "topic": 1},
        "raw2+kw2+t1": {"raw": 2, "kw": 2, "topic": 1},
        "raw3+kw1+t0.5": {"raw": 3, "kw": 1, "topic": 0.5},
        "raw2+dist3+kw1+t0.5": {"raw": 2, "distinct": 3, "kw": 1, "topic": 0.5},
        "raw2+dist2+kw1+t1": {"raw": 2, "distinct": 2, "kw": 1, "topic": 1},
        "raw1+dist2+kw0": {"raw": 1, "distinct": 2},
        "raw2+dist3+sq1+kw1+t0.5": {"raw": 2, "distinct": 3, "sq": 1, "kw": 1, "topic": 0.5},
        "v1+dist3": {"raw": 1, "topic": 1, "kw": 1, "distinct": 3},
    }
    res = []
    for name, prof in profs.items():
        cfg = dict(base, bm25_spec=best_spec, bm25_profile=prof, fusion="bm25")
        s, _ = summarize(pre, cfg)
        res.append((name, s))
    for name, s in sorted(res, key=lambda x: -x[1]["loose@k"]):
        print(f"  {fmt(s)}  {name}")

    # ---------- 2. 召回规模 ----------
    print(f"\n===== 2. raw_top_k 扫描（BM25 最优组合，fusion=bm25）=====")
    best_prof = max(profs.items(), key=lambda kv: summarize(
        pre, dict(base, bm25_spec=best_spec, bm25_profile=kv[1], fusion="bm25"))[0]["loose@k"])[0]
    p = profs[best_prof]
    print(f"  (best profile = {best_prof})")
    for k in [3, 5, 6, 8, 10, 12, 15, 20, 31]:
        s, _ = summarize(pre, dict(base, bm25_spec=best_spec, bm25_profile=p, fusion="bm25", raw_top_k=k))
        print(f"  k={k:2d} {fmt(s)}")
    print("  --- dense ---")
    for k in [3, 5, 6, 8, 10, 12, 15, 20, 31]:
        s, _ = summarize(pre, dict(base, dense_doc="problem_solution",
                                   dense_qmix={"raw_sq": 1.0}, fusion="dense", raw_top_k=k))
        print(f"  k={k:2d} {fmt(s)}")

    json.dump({"best_spec": best_spec, "best_prof": best_prof},
              open(CACHE_DIR / "sweep1_meta.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
