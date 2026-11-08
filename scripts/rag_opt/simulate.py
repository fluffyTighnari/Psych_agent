"""离线模拟器：用 precomp.pkl 的矩阵秒级复现 / 扫描任意检索配置。

配置维度：
  bm25_spec     索引规格（字段权重 + b）
  bm25_profile  查询侧词项权重 {raw, sq, kw, topic, distinct}
  dense_doc     文档向量文本规格
  dense_qmix    查询向量混合 {kind: 权重}，kind ∈ raw/sq/raw_sq/raw_sq_kw/instruct_raw_sq/instruct_raw/hyde_*
  fusion        rrf | dense | bm25 | union
  rrf_k         RRF 常数
  rerank_var    cross-encoder 输入规格
  rerank_query  传给 cross-encoder 的查询文本（raw / search）
  threshold     重排分数阈值（None = 不筛）
  raw_top_k     每路召回候选数
  final_top_k   最终条数
"""
from __future__ import annotations

import itertools
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import CACHE_DIR  # noqa: E402

PRE = None


def load():
    global PRE
    if PRE is None:
        with open(CACHE_DIR / "precomp.pkl", "rb") as f:
            PRE = pickle.load(f)
        # bm25_query 以 query 文本为键落盘，这里对齐成「按 items 下标」的列表
        if isinstance(PRE.get("bm25_query"), dict):
            PRE["bm25_query"] = [PRE["bm25_query"][it["query"]] for it in PRE["items"]]
    return PRE


DEFAULT_CFG = dict(
    bm25_spec="legacy",
    bm25_profile={"raw": 1.0, "topic": 1.0, "kw": 1.0},
    dense_doc="legacy",
    dense_qmix={"raw_sq": 1.0},
    fusion="rrf",
    rrf_k=60,
    rerank_var="legacy",
    rerank_query="raw",
    threshold=0.08,
    raw_top_k=6,
    final_top_k=3,
)


# ------------------------------------------------------------------ 召回
def bm25_scores(pre, spec, qi, profile):
    node = pre["bm25"][spec]
    order = node.get("_index")
    if order is None:
        order = {t: i for i, t in enumerate(node["tokens"])}
        node["_index"] = order
    mat = node["mat"]
    vec = np.zeros(mat.shape[1], dtype=np.float64)
    for key, w in profile.items():
        if not w:
            continue
        for tok in pre["bm25_query"][qi].get(key, []):
            i = order.get(tok)
            if i is not None:
                vec += w * mat[i]
    return vec


def dense_scores(pre, doc_variant, qmix, qi):
    vec = np.zeros_like(pre["dense_query"]["raw"][qi])
    for kind, w in qmix.items():
        if not w:
            continue
        vec = vec + w * pre["dense_query"][kind][qi]
    n = np.linalg.norm(vec)
    if n > 0:
        vec = vec / n
    return pre["dense_doc"][doc_variant] @ vec


def rerank_scores(pre, var, qi):
    return pre["rerank"][var][qi]


# ------------------------------------------------------------------ 完整流水线模拟
def run_one(pre, qi, cfg) -> list[str]:
    n = len(pre["doc_ids"])
    k = cfg["raw_top_k"]
    d = dense_scores(pre, cfg["dense_doc"], cfg["dense_qmix"], qi)
    b = bm25_scores(pre, cfg["bm25_spec"], qi, cfg["bm25_profile"])

    dense_ids = [pre["doc_ids"][i] for i in np.argsort(-d)[:k]]
    bm25_ids = [pre["doc_ids"][i] for i in np.argsort(-b)[:k]]

    fusion = cfg["fusion"]
    if fusion == "dense":
        cand = dense_ids
    elif fusion == "bm25":
        cand = bm25_ids
    elif fusion == "union":
        cand = dense_ids + [i for i in bm25_ids if i not in dense_ids]
    else:  # rrf / wrrf / rrf3
        rk = cfg["rrf_k"]
        wd = cfg.get("w_dense", 1.0)
        wb = cfg.get("w_bm25", 1.0)
        sc = {}
        lists = [(dense_ids, wd), (bm25_ids, wb)]
        if fusion == "rrf3":
            # 第三条链路：HyDE 假设文档的独立向量召回（不混进主查询向量，避免稀释）
            hq = cfg.get("dense_qmix_hyde") or {"hyde_experience": 1.0, "hyde_principle": 1.0}
            dh = dense_scores(pre, cfg["dense_doc"], hq, qi)
            lists.append(([pre["doc_ids"][i] for i in np.argsort(-dh)[:k]], cfg.get("w_hyde", 1.0)))
        for lst, w in lists:
            for pos, did in enumerate(lst):
                sc[did] = sc.get(did, 0.0) + w / (pos + rk)
        cand = [x[0] for x in sorted(sc.items(), key=lambda x: -x[1])]

    if cfg.get("rerank_var"):
        pool = cfg.get("rerank_pool") or 0
        if pool:
            cand = cand[:pool]
        r = rerank_scores(pre, cfg["rerank_var"], qi)
        idx = {did: i for i, did in enumerate(pre["doc_ids"])}
        th = cfg.get("threshold")
        mode = cfg.get("rerank_mode", "sort")
        if mode == "filter":
            # 只把 cross-encoder 当「置信度闸门」：不改变融合排名，只丢弃低于阈值的候选
            kept = [dd for dd in cand if th is None or float(r[idx[dd]]) >= th]
            return kept[: cfg["final_top_k"]]
        if mode == "blend":
            # 融合排名分（归一化）+ alpha * cross-encoder 分数
            alpha = cfg.get("blend_alpha", 0.3)
            m = max(len(cand), 1)
            rrf_norm = {dd: 1.0 - (i / m) for i, dd in enumerate(cand)}
            scored = [(dd, rrf_norm[dd] + alpha * float(r[idx[dd]])) for dd in cand]
            scored.sort(key=lambda x: -x[1])
            if th is not None:
                scored = [(dd, sc) for dd, sc in scored if float(r[idx[dd]]) >= th]
            return [dd for dd, _ in scored[: cfg["final_top_k"]]]
        scored = sorted(((did, float(r[idx[did]])) for did in cand), key=lambda x: -x[1])
        if th is not None:
            scored = [(dd, s) for dd, s in scored if s >= th]
        return [dd for dd, _ in scored[: cfg["final_top_k"]]]
    return cand[: cfg["final_top_k"]]


def summarize(pre, cfg, verbose=False):
    items = pre["items"]
    n = len(items)
    agg = dict(loose=0, strict=0, mrr=0.0, neg=0, neg_before=0, cov=0.0, cnt=0)
    detail = []
    for qi, it in enumerate(items):
        top = run_one(pre, qi, cfg)
        tgt = set(it["target_doc_ids"])
        negs = set(it["hard_negatives"])
        prim = it["primary_target"]
        hit = [d for d in top if d in tgt]
        agg["loose"] += 1 if hit else 0
        agg["strict"] += 1 if prim in top else 0
        agg["mrr"] += (1.0 / (top.index(prim) + 1)) if prim in top else 0.0
        agg["neg"] += sum(1 for d in top if d in negs)
        agg["cov"] += (len(set(top) & tgt) / len(tgt)) if tgt else 0.0
        agg["cnt"] += len(top)
        vr = [i for i, d in enumerate(top) if d in tgt]
        nr = [i for i, d in enumerate(top) if d in negs]
        if vr and nr and min(nr) < max(vr):
            agg["neg_before"] += 1
        detail.append({"qi": qi, "top": top, "loose": bool(hit), "strict": prim in top})
        if verbose and not hit:
            print(f"   MISS qi={qi} top={[d[:8] for d in top]} tgt={[d[:8] for d in tgt]} | {it['query'][:30]}")
    return {
        "loose@k": round(agg["loose"] / n, 4),
        "strict@k": round(agg["strict"] / n, 4),
        "mrr": round(agg["mrr"] / n, 4),
        "cov@k": round(agg["cov"] / n, 4),
        "neg@k": agg["neg"],
        "neg_before": agg["neg_before"],
        "cnt": round(agg["cnt"] / n, 2),
    }, detail


def fmt(s):
    return (f"loose={s['loose@k']:.3f} strict={s['strict@k']:.3f} mrr={s['mrr']:.3f} "
            f"cov={s['cov@k']:.3f} neg={s['neg@k']:2d} neg_before={s['neg_before']:2d} cnt={s['cnt']:.2f}")


def grid(base, **axes):
    """笛卡尔积扫描，返回按 (loose, strict, -neg) 排序的结果列表。"""
    pre = load()
    keys = list(axes)
    rows = []
    for combo in itertools.product(*[axes[k] for k in keys]):
        cfg = dict(base)
        cfg.update(dict(zip(keys, combo)))
        s, _ = summarize(pre, cfg)
        rows.append((cfg, s))
    return rows


if __name__ == "__main__":
    pre = load()
    print("=== 校验：模拟 vs 真实基线（应完全一致） ===")
    s, det = summarize(pre, DEFAULT_CFG, verbose=True)
    print("sim :", fmt(s))
    import json
    rows = json.load(open(CACHE_DIR / "baseline_full_rows.json", encoding="utf-8"))
    real = {
        "loose@k": round(sum(1 for r in rows if r["loose"]) / len(rows), 4),
        "strict@k": round(sum(1 for r in rows if r["strict"]) / len(rows), 4),
        "mrr": round(sum(r["mrr"] for r in rows) / len(rows), 4),
        "cov@k": round(sum(r["cov"] for r in rows) / len(rows), 4),
        "neg@k": sum(r["neg"] for r in rows),
        "neg_before": sum(r["neg_before"] for r in rows),
        "cnt": round(sum(r["final_count"] for r in rows) / len(rows), 2),
    }
    print("real:", fmt(real))
