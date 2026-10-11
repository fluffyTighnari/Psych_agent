import threading
import jieba
from typing import List

from core.helper.trace_tracker import GLOBAL_TRACKER


class Retriever:
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
        cut_words = list(jieba.cut(raw_query))
        bm25_tokens = cut_words + topic_list + keywords_list
        ids_list = self.BM25.search(bm25_tokens, top_k)
        GLOBAL_TRACKER.add_trace(
            stage="retrieve_sparse",
            label="BM25稀疏检索完成",
            content={"query": raw_query[:80], "topics": topic_list, "keywords": keywords_list,
                     "top_k": top_k, "hit_ids": ids_list}
        )
        return ids_list

    def rrf_fuse(self, dense_ids: List[str], bm25_ids: List[str], k=60) -> List[str]:
        """RRF倒数排名融合，替代交集取并集加权排序"""
        rank_score = {}
        for pos, doc_id in enumerate(dense_ids):
            score = 1 / (pos + k)
            rank_score[doc_id] = rank_score.get(doc_id, 0) + score
        for pos, doc_id in enumerate(bm25_ids):
            score = 1 / (pos + k)
            rank_score[doc_id] = rank_score.get(doc_id, 0) + score
        sorted_items = sorted(rank_score.items(), key=lambda x: x[1], reverse=True)
        return [item[0] for item in sorted_items]

    def retrieve(self, query: str, raw_top_k=6, final_top_k=3):
        """
        完整检索入口：并行稠密+稀疏 → RRF融合 → 重排
        :param query: 用户原始提问
        :param raw_top_k: 两路粗排召回数量，放大素材
        :param final_top_k: 重排后最终返回条数
        :return: 重排后的Document列表
        """
        opt_data = self.prompt_optimizer.optimize_prompt(query)
        GLOBAL_TRACKER.add_trace(
            stage="optimize_prompt",
            label="Query优化完成",
            content={"search_query": opt_data["search_query"],
                     "match_topics": opt_data["match_topics"],
                     "keywords": opt_data["keywords"]}
        )
        search_q = opt_data["search_query"] + query
        match_topics = opt_data["match_topics"]
        keywords = opt_data["keywords"]

        dense_ids = []
        bm25_ids = []

        t1 = threading.Thread(target=lambda: dense_ids.extend(self.retrieve_summary(search_q, raw_top_k)))
        t2 = threading.Thread(target=lambda: bm25_ids.extend(self.retrieve_topics(query, match_topics, keywords, raw_top_k)))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        fused_doc_ids = self.rrf_fuse(dense_ids, bm25_ids)
        GLOBAL_TRACKER.add_trace(
            stage="retrieve_fusion",
            label="RRF双路融合完成",
            content={"dense_count": len(dense_ids), "sparse_count": len(bm25_ids),
                     "fused_count": len(fused_doc_ids), "fused_ids": fused_doc_ids}
        )
        if not fused_doc_ids:
            GLOBAL_TRACKER.add_trace(
                stage="retrieve_fusion",
                label="无匹配文档",
                content={}
            )
            return []

        knowledge_list = self.knowledge_loader.load_knowledge(fused_doc_ids)
        final_list = self.reranker.rerank_documents(query, knowledge_list, final_top_k)
        GLOBAL_TRACKER.add_trace(
            stage="retrieve_final",
            label="最终知识列表",
            content={"final_count": len(final_list), "doc_ids": [doc.doc_id for doc in final_list]}
        )
        return final_list
