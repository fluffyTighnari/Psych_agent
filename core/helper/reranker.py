from sentence_transformers import CrossEncoder

from core.helper.trace_tracker import current_tracker


class Reranker:
    def __init__(self, model_path, score_threshold: float = 0.08):
        self.model = CrossEncoder(str(model_path))
        self.score_threshold = score_threshold

    def rerank_documents(self, query, documents, top_k=3, score_threshold=None):
        if not documents:
            return []

        # 显式传入 score_threshold 时以传入值为准（检索调试台需要对比不同阈值的效果）；
        # 不传（None）时沿用实例默认 self.score_threshold，保持生产链路行为不变。
        threshold = self.score_threshold if score_threshold is None else float(score_threshold)

        def build_input_text(doc):
            text_parts = [doc.summary]
            if doc.doc_type == "weekly":
                text_parts.append(doc.problem)
                text_parts.append(doc.solution)
            else:
                text_parts.append(doc.content[:800])
            return "\n".join(text_parts)

        pairs = [(query, build_input_text(doc)) for doc in documents]
        scores = self.model.predict(pairs)

        score_doc_pairs = list(zip(scores, documents))

        before_count = len(score_doc_pairs)
        score_doc_pairs.sort(key=lambda x: x[0], reverse=True)

        filtered_pairs = [
            (score, doc) for score, doc in score_doc_pairs
            if score >= threshold
        ]

        # current_tracker()：调试请求期间会返回请求本地 trace，避免污染全局实时日志
        current_tracker().add_trace(
            stage="rerank",
            label="交叉编码器重排过滤完成",
            content={
                "threshold": threshold,
                "before_count": before_count,
                "after_count": len(filtered_pairs),
                "doc_with_score": [
                    {"doc_id": d.doc_id, "summary": d.summary[:60], "score": round(float(s), 4)}
                    for s, d in score_doc_pairs
                ]
            }
        )

        if not filtered_pairs:
            return []

        ranked_docs = [doc for _, doc in filtered_pairs]
        return ranked_docs[:top_k]
