"""一次性探测脚本：验证组件可加载、向量库计数、optimizer 输出、pipeline 可跑通。"""
import sys, os, json, time
sys.path.insert(0, os.path.abspath("."))

from core.helper.knowledge_cache import KNOWLEDGE_CACHE
print("knowledge docs:", len(KNOWLEDGE_CACHE.documents))

from core.helper.retrieval_pipeline import get_retrieval_components
t0 = time.time()
comps = get_retrieval_components()
print("components loaded in %.1fs" % (time.time() - t0))
print("vector count:", comps["vector_db"].count())
print("bm25 doc_id_list:", len(comps["bm25"].doc_id_list))
print("bm25 avgdl:", comps["bm25"].bm25.avgdl)
print("bm25 vocab:", len(comps["bm25"].bm25.idf))
print("sample corpus tokens:", comps["bm25"].corpus_tokenized[0])
print("corpus lens:", [len(c) for c in comps["bm25"].corpus_tokenized])

# vector db ids vs knowledge ids
stored = comps["vector_db"].collection.get(include=[])["ids"]
kb_ids = set(doc.doc_id for doc in KNOWLEDGE_CACHE.documents)
print("stored==kb:", set(stored) == kb_ids, "stored only:", set(stored) - kb_ids, "kb only:", kb_ids - set(stored))

q = "我经常回想以前，想'如果当初选了另一条路，现在会不会不一样'。这种念头一冒出来就停不下来，越想越后悔，也知道想这些没用。怎么才能真的放下过去，不再被'假如'困住？"
t0 = time.time()
opt = comps["prompt_optimizer"].optimize_prompt(q)
print("optimizer %.1fs:" % (time.time() - t0), json.dumps(opt, ensure_ascii=False))

t0 = time.time()
from core.helper.retrieval_pipeline import run_pipeline
res = run_pipeline(q, final_top_k=3)
print("pipeline %.1fs" % (time.time() - t0))
print("final:", res["final"]["doc_ids"], res["final"]["source"])
for s in res["stages"]:
    print(" ", s["name"], s["output_count"], [r["doc_id"][:8] for r in s["results"]], [r["score"] for r in s["results"]])
