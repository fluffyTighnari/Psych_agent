"""扫描 7：隔离「optimizer 提示词 v1 → v2」的净收益。

做法：把 v1 提示词的 31 条 LLM 输出（baseline 跑批留下的磁盘缓存）与 v2 输出放到
同一个富索引 / 同一套 dense 文档向量上对比，消除索引与模型差异。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import CACHE_DIR, TMP_DIR  # noqa
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

from config.model_config import EMBEDDING_MODEL  # noqa
from core.embedding.embedding import EmbeddingModel  # noqa
from core.helper.BM25 import BM25TagIndexer  # noqa
from core.helper.knowledge_cache import KNOWLEDGE_CACHE  # noqa
from core.helper import retrieval_config as RC  # noqa

import jieba

pre = load()
items = pre["items"]
docs = list(KNOWLEDGE_CACHE.documents)

v1 = json.load(open(CACHE_DIR / "opt_baseline_a45b0eba5f.json", encoding="utf-8"))


def q_of(it):
    return hashlib.md5(it["query"].encode("utf-8")).hexdigest()


v1_opt = {it["query"]: v1[q_of(it)] for it in items}
v2_opt = pre["opt"]


def toks(raw):
    return [w for w in jieba.cut(raw or "") if w.strip()]


def qtok(optmap):
    return {
        it["query"]: {
            "raw": toks(it["query"]),
            "kw": [w for k in (optmap[it["query"]].get("keywords") or []) for w in toks(k)],
            "topic": [str(t).strip().lower() for t in (optmap[it["query"]].get("match_topics") or [])],
            "distinct": [w for k in (optmap[it["query"]].get("distinctive_terms") or []) for w in toks(k)],
            "sq": toks(optmap[it["query"]].get("search_query") or ""),
        }
        for it in items
    }


def build_contrib():
    idx = BM25TagIndexer(documents=docs, bm25_path=str(TMP_DIR / "bm25_cmp.pkl"),
                         field_weights=RC.BM25_FIELD_WEIGHTS, k1=RC.BM25_K1, b=RC.BM25_B)
    vocab = sorted({t for m in (qtok(v1_opt), qtok(v2_opt)) for q in m.values() for k in q for t in q[k]})
    mat = np.zeros((len(vocab), len(docs)))
    for i, t in enumerate(vocab):
        mat[i] = idx.bm25.get_scores([t])
    return {"tokens": vocab, "mat": mat, "_index": {t: i for i, t in enumerate(vocab)}}


print("building contrib matrix ...")
pre.setdefault("bm25", {})["bm25_cmp"] = build_contrib()

emb = EmbeddingModel(EMBEDDING_MODEL)
for name, optmap in (("v1", v1_opt), ("v2", v2_opt)):
    pre[f"dense_query_{name}"] = {}
    pre[f"dense_query_{name}"]["raw"] = np.asarray(
        emb.model.encode([it["query"] for it in items], normalize_embeddings=True))
    pre[f"dense_query_{name}"]["sq"] = np.asarray(
        emb.model.encode([optmap[it["query"]].get("search_query") or "" for it in items],
                         normalize_embeddings=True))
    pre[f"dense_query_{name}"]["raw_sq"] = np.asarray(
        emb.model.encode([f'{optmap[it["query"]].get("search_query") or ""} {it["query"]}' for it in items],
                         normalize_embeddings=True))

# 把 v1/v2 的查询词项挂进 pre，供临时 sim 使用
BASE = dict(DEFAULT_CFG, rerank_var=None, threshold=None, fusion="wrrf", rrf_k=3,
            w_dense=1.0, w_bm25=2.0, raw_top_k=15, dense_doc="problem_solution",
            dense_qmix={"raw": 1.0, "sq": 0.5},
            bm25_spec="bm25_cmp")

PROFILES = {
    "v2权重(raw1,kw0.5,t1)": {"raw": 1.0, "kw": 0.5, "topic": 1.0},
    "v1原样(raw1,kw1,t1)": {"raw": 1.0, "kw": 1.0, "topic": 1.0},
    "v2+distinct": {"raw": 1.0, "kw": 0.5, "topic": 1.0, "distinct": 1.0},
}

print("\n===== A. 只换 optimizer 提示词（BM25 侧；dense 侧固定用 raw+sq）=====")
rows = []
for ver, optmap in (("v1", v1_opt), ("v2", v2_opt)):
    pre["bm25_query"] = [qtok(optmap)[it["query"]] for it in items]
    for pname, p in PROFILES.items():
        if ver == "v1" and pname.startswith("v2"):
            continue
        s, _ = summarize(pre, dict(BASE, bm25_profile=p))
        rows.append((f"prompt={ver} profile={pname}", s))
for tag, s in rows:
    print(f"  {fmt(s)}  {tag}")

print("\n===== B. 只换 optimizer 提示词（dense 侧）=====")
for ver, optmap in (("v1", v1_opt), ("v2", v2_opt)):
    pre["dense_query"] = pre[f"dense_query_{ver}"]
    for qk in ["raw", "raw_sq"]:
        s, _ = summarize(pre, dict(BASE, dense_qmix={qk: 1.0}, fusion="dense"))
        print(f"  {fmt(s)}  prompt={ver} dense={qk}")
