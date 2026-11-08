from sentence_transformers import SentenceTransformer

from core.helper.retrieval_config import DENSE_DOC_VARIANT
from core.helper.retrieval_text import dense_doc_text


class EmbeddingModel:
    def __init__(self, model_path):
        self.model = SentenceTransformer(str(model_path))

    def encode(self, text):
        return self.model.encode(
            text,
            normalize_embeddings=True
        )

    def encode_documents(self, documents, variant: str = DENSE_DOC_VARIANT):
        """按统一规格把 Document 编码成向量（规格见 core/helper/retrieval_text.py）。

        注意：换规格后必须重建向量库（`VectorDB.sync_all_documents`），否则库里的旧向量
        与检索时的查询向量不在同一语义口径上。
        """
        texts = [dense_doc_text(doc, variant) for doc in documents]
        if not texts:
            return []
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return [v for v in vectors]
