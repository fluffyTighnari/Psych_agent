from sentence_transformers import SentenceTransformer


class EmbeddingModel:
    def __init__(self, model_path):
        self.model = SentenceTransformer(str(model_path))

    def encode(self, text):
        return self.model.encode(
            text,
            normalize_embeddings=True
        )

    def encode_documents(self, documents):
        vectors = []
        for doc in documents:
            # weekly（原理类）文档含结构化 problem/analysis/solution，标题+摘要一起编码更能体现语义
            if doc.doc_type == "weekly":
                text = f"{doc.title}\n\n{doc.summary}"
            else:
                text = doc.summary
            vectors.append(
                self.encode(text)
            )
        return vectors