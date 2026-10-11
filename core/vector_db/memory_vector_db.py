import chromadb
from chromadb.config import Settings
from typing import List
import numpy as np

from core.schema import Memory
from core.helper.trace_tracker import GLOBAL_TRACKER


class MemoryVectorDB:
    def __init__(self, db_path, collection_name):
        self.client = chromadb.PersistentClient(
            path=str(db_path),
            settings=Settings(allow_reset=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name
        )

    def count(self):
        return self.collection.count()

    def upsert_memories(self, memories: List[Memory], embeddings: List[np.ndarray]):
        if not memories:
            return
        ids_batch = []
        vectors_batch = []
        for m, emb in zip(memories, embeddings):
            ids_batch.append(m.id)
            vectors_batch.append(emb.tolist())
        self.collection.upsert(ids=ids_batch, embeddings=vectors_batch)
        GLOBAL_TRACKER.add_trace(
            stage="memory_vector_db",
            label="Memory向量库upsert完成",
            content={"count": len(ids_batch), "total": self.collection.count()}
        )

    def query(self, embedding, top_k: int = 3, score_threshold: float = 0.65):
        if self.collection.count() == 0:
            return {"ids": [[]], "distances": [[]]}
        res = self.collection.query(
            query_embeddings=[embedding.tolist()],
            n_results=min(top_k, self.collection.count())
        )
        ids_list = res["ids"][0]
        distances = res["distances"][0]
        filtered_ids = []
        for did, dist in zip(ids_list, distances):
            similarity = 1 - (dist / 2)
            if similarity >= score_threshold:
                filtered_ids.append(did)
        return filtered_ids
