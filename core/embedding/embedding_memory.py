from sentence_transformers import SentenceTransformer


class MemoryEmbedding:
    def __init__(self, model_path):
        self.model = SentenceTransformer(str(model_path))

    def encode(self, text):
        return self.model.encode(text, normalize_embeddings=True)

    def encode_memories(self, memories):
        vectors = []
        for m in memories:
            text = f"{m.title}\n{m.summary}"
            vectors.append(self.encode(text))
        return vectors
