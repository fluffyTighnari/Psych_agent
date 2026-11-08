import threading
from typing import List

import jieba

from core.helper import retrieval_config as RC
from core.helper.retrieval_text import bm25_query_tokens, dense_query_texts
from core.helper.trace_tracker import GLOBAL_TRACKER


class Retriever:
    """生产检索入口（RAG_agent 使用）。

    v2 优化后的实现直接复用调试流水线 ``RetrievalPipeline`` 的同一套算法与默认参数
    （富索引 BM25 / 多向量 dense / 加权 RRF / blend 重排），保证「调试台看到的排名」
    与「线上真实排名」永远一致；此前两条链路的参数是各写一份、容易漂移。
    """

    def __init__(
            self,
            embedding_model,
            vector_db,
            bm25,
            prompt_optimizer,
            knowledge_loader,
            reranker,
    ):
        self.embedding_model = embedding_model
        self.vector_db = vector_db
        self.BM25 = bm25
        self.prompt_optimizer = prompt_optimizer
        self.knowledge_loader = knowledge_loader
        self.reranker = reranker

    # ---------- 兼容保留的细粒度方法（供外部按需单独调用） ----------

    def retrieve_summary(self, optimized_query: str, top_k: int):
        embedding = self.embedding_model.encode(optimized_query)
        res = self.vector_db.query(embedding, top_k)
        ids_list = res["ids"][0]
        GLOBAL_TRACKER.add_trace(
            stage="retrieve_dense",
            label="稠密向量检索完成",
            content={"query": optimized_query[:80], "top_k": top_k, "hit_ids": ids_list}
        )
        return ids_list

    def retrieve_topics(self, raw_query: str, topic_list: List[str], keywords_list: list[str], top_k: int):
        bm25_tokens = bm25_query_tokens(
            raw_query,
            {"match_topics": topic_list, "keywords": keywords_list},
        )
        ids_list = self.BM25.search(bm25_tokens, top_k)
        GLOBAL_TRACKER.add_trace(
            stage="retrieve_sparse",
            label="BM25稀疏检索完成",
            content={"query": raw_query[:80], "topics": topic_list, "keywords": keywords_list,
                     "top_k": top_k, "hit_ids": ids_list}
        )
        return ids_list

    @staticmethod
    def rrf_fuse(dense_ids: List[str], bm25_ids: List[str], k: int = RC.DEFAULT_RRF_K) -> List[str]:
        """加权倒数排名融合（默认 w_dense = w_bm25 = 1、k = 3，与流水线一致）。"""
        rank_score = {}
        for lst, weight in ((dense_ids, RC.DEFAULT_W_DENSE), (bm25_ids, RC.DEFAULT_W_BM25)):
            for pos, doc_id in enumerate(lst):
                rank_score[doc_id] = rank_score.get(doc_id, 0) + weight / (pos + k)
        sorted_items = sorted(rank_score.items(), key=lambda x: x[1], reverse=True)
        return [item[0] for item in sorted_items]

    # ---------- 主入口 ----------

    def retrieve(self, query: str, raw_top_k=RC.DEFAULT_RAW_TOP_K, final_top_k=RC.DEFAULT_FINAL_TOP_K):
        """
        完整检索入口：Query 优化 → 稠密 + 稀疏召回 → 加权 RRF 融合 → Cross-Encoder 精排

        算法与默认参数全部来自 ``core/helper/retrieval_config.py`` 与
        ``core/helper/retrieval_pipeline.py``，与调试台 /api/retrieval/debug 完全一致。

        :param query: 用户原始提问
        :param raw_top_k: 两路粗排召回数量
        :param final_top_k: 最终返回条数
        :return: Document 列表（按最终排名）
        """
        from core.helper.retrieval_pipeline import RetrievalPipeline

        pipeline = RetrievalPipeline(
            embedding_model=self.embedding_model,
            vector_db=self.vector_db,
            bm25=self.BM25,
            prompt_optimizer=self.prompt_optimizer,
            knowledge_loader=self.knowledge_loader,
            reranker=self.reranker,
        )
        result = pipeline.run(
            query,
            raw_top_k=raw_top_k,
            final_top_k=final_top_k,
            trace=GLOBAL_TRACKER,
        )
        doc_ids = list((result.get("final") or {}).get("doc_ids") or [])
        if not doc_ids:
            return []

        docs = self.knowledge_loader.load_knowledge(doc_ids) or []
        by_id = {str(getattr(doc, "doc_id", "")): doc for doc in docs}
        if len(by_id) < len(doc_ids):
            # 兜底：id_map 跨平台失效时用 KNOWLEDGE_CACHE 补齐（与流水线同一策略）
            from core.helper.knowledge_cache import KNOWLEDGE_CACHE

            cache = getattr(KNOWLEDGE_CACHE, "cache", None) or {}
            for key in doc_ids:
                if key not in by_id and key in cache:
                    by_id[key] = cache[key]

        final_list = [by_id[key] for key in doc_ids if key in by_id]
        GLOBAL_TRACKER.add_trace(
            stage="retrieve_final",
            label="最终知识列表",
            content={"final_count": len(final_list), "doc_ids": [doc.doc_id for doc in final_list]}
        )
        return final_list
