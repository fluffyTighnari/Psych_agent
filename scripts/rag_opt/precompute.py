"""一次性预计算：把三路召回里所有「昂贵且与调参无关」的部分算成矩阵并落盘。

分块增量落盘（.cache/precomp.pkl）：
  doc_ids / items / opt / bm25 / bm25_query / dense_doc / dense_query / rerank
重跑时已存在的块会复用（--force 可强制重算），因为 cross-encoder 打分很慢。

有了这些矩阵，任意「索引规格 × 查询词项权重 × 召回 top-k × 融合方式 × 阈值」组合都能在
秒级内离线模拟，无需重复推理。
"""
from __future__ import annotations

import argparse
import hashlib
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import CACHE_DIR, TMP_DIR, CachedOptimizer, load_dataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.model_config import EMBEDDING_MODEL, GLOBAL_MODEL, RERANKING_MODEL  # noqa: E402
from config.prompt_config import optimizer_prompt  # noqa: E402
from core.embedding.embedding import EmbeddingModel  # noqa: E402
from core.helper.BM25 import BM25TagIndexer  # noqa: E402
from core.helper.knowledge_cache import KNOWLEDGE_CACHE  # noqa: E402
from core.helper.prompt_optimizer import PromptOptimizer  # noqa: E402
from core.helper.reranker import Reranker  # noqa: E402
from core.llm import LLM  # noqa: E402

import jieba  # noqa: E402

OUT = CACHE_DIR / "precomp.pkl"

BM25_SPECS: dict[str, dict] = {
    "legacy": dict(field_weights=None),
    "rich_b20": dict(field_weights=dict(topic=3, keyword=2, title=3, summary=2, problem=2, solution=2, analysis=1, content=1), b=0.2),
    "rich_b40": dict(field_weights=dict(topic=3, keyword=2, title=3, summary=2, problem=2, solution=2, analysis=1, content=1), b=0.4),
    "rich_b60": dict(field_weights=dict(topic=3, keyword=2, title=3, summary=2, problem=2, solution=2, analysis=1, content=1), b=0.6),
    "rich_b75": dict(field_weights=dict(topic=3, keyword=2, title=3, summary=2, problem=2, solution=2, analysis=1, content=1), b=0.75),
    "rich_notopic_b40": dict(field_weights=dict(keyword=2, title=3, summary=2, problem=2, solution=2, analysis=1, content=1), b=0.4),
    "raw_only_b40": dict(field_weights=dict(title=1, problem=1, solution=1, analysis=1, content=1), b=0.4),
    "construct_only_b40": dict(field_weights=dict(topic=3, keyword=2, title=3, summary=2), b=0.4),
    "rich_body2_b40": dict(field_weights=dict(topic=3, keyword=2, title=3, summary=2, problem=2, solution=2, analysis=1, content=2), b=0.4),
    "rich_specific_b40": dict(field_weights=dict(topic=1, keyword=4, title=4, summary=2, problem=4, solution=4, analysis=1, content=1), b=0.4),
}

DENSE_DOC_VARIANTS = ["legacy", "title_summary_kw", "problem_solution", "rich", "full"]
DENSE_QUERY_KINDS = ["raw", "sq", "raw_sq", "raw_sq_kw", "instruct_raw_sq", "instruct_raw"]
RERANK_VARIANTS = ["legacy", "with_kw", "problem_solution"]


def bm25_tokens(raw: str) -> list[str]:
    return [w for w in jieba.cut(raw or "") if w.strip()]


def load_pre() -> dict:
    if OUT.exists():
        with open(OUT, "rb") as f:
            return pickle.load(f)
    return {}


def save_pre(pre: dict):
    with open(OUT, "wb") as f:
        pickle.dump(pre, f)
    print(f"  [saved {OUT.stat().st_size/1e6:.1f} MB]")


# ---------------------------------------------------------------- 各块
def build_base(pre, force=False):
    dataset = load_dataset()
    items = dataset["items"]
    docs = list(KNOWLEDGE_CACHE.documents)
    if not force and pre.get("items") and pre.get("doc_ids") == [d.doc_id for d in docs]:
        print("base: reuse")
        return
    pre["items"] = items
    pre["doc_ids"] = [d.doc_id for d in docs]
    pre["doc_meta"] = [
        {"doc_id": d.doc_id, "type": d.doc_type, "title": d.title, "len": len(d.content or "")}
        for d in docs
    ]
    ver = hashlib.md5(optimizer_prompt.encode("utf-8")).hexdigest()[:10]
    opt = CachedOptimizer(PromptOptimizer(LLM(GLOBAL_MODEL.small)), ver, "precomp")
    t0 = time.time()
    pre["opt"] = {it["query"]: opt.optimize_prompt(it["query"]) for it in items}
    opt.flush()
    pre["prompt_version"] = ver
    print(f"base: optimizer {time.time()-t0:.1f}s hits={opt.hits} misses={opt.misses} ver={ver}")
    pre["bm25_query"] = {
        it["query"]: {
            "raw": bm25_tokens(it["query"]),
            "sq": bm25_tokens(pre["opt"][it["query"]].get("search_query") or ""),
            "kw": [w for k in (pre["opt"][it["query"]].get("keywords") or []) for w in bm25_tokens(k)],
            "topic": [str(t).strip().lower() for t in (pre["opt"][it["query"]].get("match_topics") or [])],
            "distinct": [w for k in (pre["opt"][it["query"]].get("distinctive_terms") or []) for w in bm25_tokens(k)],
        }
        for it in items
    }
    save_pre(pre)


def build_bm25(pre, force=False):
    docs = list(KNOWLEDGE_CACHE.documents)
    if not force and pre.get("bm25", {}).keys() >= set(BM25_SPECS):
        print("bm25: reuse")
        return
    pre.setdefault("bm25", {})
    for name, spec in BM25_SPECS.items():
        if not force and name in pre["bm25"]:
            continue
        t0 = time.time()
        idx = BM25TagIndexer(documents=docs, bm25_path=str(TMP_DIR / f"bm25_{name}.pkl"), **spec)
        vocab = sorted({t for qt in pre["bm25_query"].values() for key in qt for t in qt[key]})
        mat = np.zeros((len(vocab), len(docs)), dtype=np.float64)
        for i, tok in enumerate(vocab):
            mat[i] = idx.bm25.get_scores([tok])
        pre["bm25"][name] = {"tokens": vocab, "mat": mat, "spec": dict(idx.index_spec),
                             "avgdl": float(idx.bm25.avgdl), "vocab_size": len(idx.bm25.idf)}
        print(f"  bm25 {name:20s} vocab={len(idx.bm25.idf):5d} avgdl={idx.bm25.avgdl:7.1f} {time.time()-t0:.1f}s")
    save_pre(pre)


def build_dense(pre, force=False):
    from scripts.rag_opt.precompute_text import doc_text, query_text  # noqa
    if not force and pre.get("dense_doc") and pre.get("dense_query"):
        print("dense: reuse")
        return
    emb = EmbeddingModel(EMBEDDING_MODEL)
    docs = list(KNOWLEDGE_CACHE.documents)
    items = pre["items"]
    pre["dense_doc"] = {}
    for v in DENSE_DOC_VARIANTS:
        pre["dense_doc"][v] = np.asarray(
            emb.model.encode([doc_text(d, v) for d in docs], normalize_embeddings=True))
    pre["dense_query"] = {}
    for k in DENSE_QUERY_KINDS:
        pre["dense_query"][k] = np.asarray(
            emb.model.encode([query_text(it["query"], pre["opt"][it["query"]], k) for it in items],
                             normalize_embeddings=True))
    for k in ("hyde_experience", "hyde_principle"):
        texts = [pre["opt"][it["query"]].get(k) or "" for it in items]
        if all(texts):
            pre["dense_query"][k] = np.asarray(emb.model.encode(texts, normalize_embeddings=True))
    print("  dense ok:", list(pre["dense_query"]))
    save_pre(pre)


def build_rerank(pre, force=False, variants=None):
    from scripts.rag_opt.precompute_text import rerank_text  # noqa
    rr = Reranker(RERANKING_MODEL)
    docs = list(KNOWLEDGE_CACHE.documents)
    items = pre["items"]
    pre.setdefault("rerank", {})
    for v in (variants or RERANK_VARIANTS):
        if not force and v in pre["rerank"]:
            continue
        mat = np.zeros((len(items), len(docs)), dtype=np.float32)
        t0 = time.time()
        for qi, it in enumerate(items):
            mat[qi] = np.asarray(rr.model.predict([(it["query"], rerank_text(d, v)) for d in docs]),
                                 dtype=np.float32)
        pre["rerank"][v] = mat
        print(f"  rerank {v:18s} {time.time()-t0:.1f}s")
        save_pre(pre)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default="", help="base,bm25,dense,rerank")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else {"base", "bm25", "dense", "rerank"}
    t0 = time.time()
    pre = load_pre()
    if "base" in only:
        build_base(pre, a.force)
    if "bm25" in only:
        build_bm25(pre, a.force)
    if "dense" in only:
        build_dense(pre, a.force)
    if "rerank" in only:
        build_rerank(pre, a.force)
    save_pre(pre)
    print(f"done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
