"""验证 lite 提示词（不生成 HyDE）是否影响检索质量：与完整 v2 提示词在同一索引上对比。

做法：对 31 条 query 跑 lite 提示词（磁盘缓存），使用现有富索引计算 BM25 贡献矩阵，
再用与 sweep11 相同的最终配置做离线模拟对比。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import CACHE_DIR, TMP_DIR, load_dataset  # noqa
from simulate import DEFAULT_CFG, fmt, load, summarize  # noqa

from config.model_config import EMBEDDING_MODEL, GLOBAL_MODEL  # noqa
from config.prompt_config import optimizer_prompt_lite  # noqa
from core.embedding.embedding import EmbeddingModel  # noqa
from core.helper.BM25 import BM25TagIndexer  # noqa
from core.helper import retrieval_config as RC  # noqa
from core.helper.knowledge_cache import KNOWLEDGE_CACHE  # noqa
from core.helper.prompt_optimizer import PromptOptimizer  # noqa
from core.llm import LLM  # noqa

import jieba

pre = load()
items = pre["items"]
docs = list(KNOWLEDGE_CACHE.documents)

ver = hashlib.md5(optimizer_prompt_lite.encode("utf-8")).hexdigest()[:10]
cache_path = CACHE_DIR / f"opt_lite_{ver}.json"
store = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
opt = PromptOptimizer(LLM(GLOBAL_MODEL.small))

t0 = time.time()
hits = 0
for it in items:
    k = hashlib.md5(it["query"].encode("utf-8")).hexdigest()
    if k in store:
        hits += 1
        continue
    store[k] = opt.optimize_prompt(it["query"], want_hyde=False)
    cache_path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"lite optimizer: hits={hits} new={len(store)-hits} in {time.time()-t0:.1f}s "
      f"(avg {(time.time()-t0)/max(len(store)-hits,1):.2f}s/query)")

full = pre["opt"]
lite = {it["query"]: store[hashlib.md5(it["query"].encode("utf-8")).hexdigest()] for it in items}


def toks(raw):
    return [w for w in jieba.cut(raw or "") if w.strip()]


def qtok(optmap):
    return [{
        "raw": toks(it["query"]),
        "kw": [w for k in (optmap[it["query"]].get("keywords") or []) for w in toks(k)],
        "topic": [str(t).strip().lower() for t in (optmap[it["query"]].get("match_topics") or [])],
        "distinct": [w for k in (optmap[it["query"]].get("distinctive_terms") or []) for w in toks(k)],
        "sq": toks(optmap[it["query"]].get("search_query") or ""),
    } for it in items]


idx = BM25TagIndexer(documents=docs, bm25_path=str(TMP_DIR / "bm25_lite.pkl"),
                     field_weights=RC.BM25_FIELD_WEIGHTS, k1=RC.BM25_K1, b=RC.BM25_B)
qmap = {"full": qtok(full), "lite": qtok(lite)}
vocab = sorted({t for m in qmap.values() for q in m for k in q for t in q[k]})
mat = np.zeros((len(vocab), len(docs)))
for i, t in enumerate(vocab):
    mat[i] = idx.bm25.get_scores([t])
pre["bm25"]["lite_cmp"] = {"tokens": vocab, "mat": mat,
                           "_index": {t: i for i, t in enumerate(vocab)}}

emb = EmbeddingModel(EMBEDDING_MODEL)
for name, om in (("full", full), ("lite", lite)):
    pre[f"dq_{name}"] = {
        "raw": np.asarray(emb.model.encode([it["query"] for it in items], normalize_embeddings=True)),
        "sq": np.asarray(emb.model.encode([om[it["query"]].get("search_query") or "" for it in items],
                                          normalize_embeddings=True)),
    }

FINAL = dict(DEFAULT_CFG, bm25_spec="lite_cmp", bm25_profile={"raw": 1.0, "kw": 0.5, "topic": 1.0},
             dense_doc="problem_solution", dense_qmix={"raw": 1.0, "sq": 0.5},
             fusion="wrrf", rrf_k=3, w_dense=1.0, w_bm25=1.0, raw_top_k=15,
             rerank_var="legacy", rerank_mode="blend", blend_alpha=0.3, rerank_pool=10, threshold=None)

print("\n===== 完整 v2（含 HyDE 字段） vs lite（不生成 HyDE）=====")
for name in ("full", "lite"):
    pre["bm25_query"] = qmap[name]
    pre["dense_query"] = pre[f"dq_{name}"]
    s, _ = summarize(pre, FINAL)
    print(f"  {name:5s} {fmt(s)}")
