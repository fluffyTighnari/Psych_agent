import chromadb
from chromadb.config import Settings
from typing import List, Set
import numpy as np

from core.schema import Document
from core.helper.trace_tracker import GLOBAL_TRACKER


class VectorDB:

    def __init__(self, db_path, collection_name):

        self.client = chromadb.PersistentClient(
            path=str(db_path),
            settings = Settings(allow_reset=False)
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name
        )

    def count(self):
        return self.collection.count()

    def sync_all_documents(self, documents: List[Document], embeddings: List[np.ndarray]):
        """
        增量同步：自动处理【新增/修改/本地删除】，不重建全库
        :param documents: DocumentLoader加载的全部本地有效文档
        :param embeddings: 对应每条document的嵌入向量
        """
        current_ids: Set[str] = set()
        ids_batch = []
        vectors_batch = []
        skipped = 0

        for doc, emb in zip(documents, embeddings):
            if not doc.doc_id:
                # 双保险：doc_id 为空时跳过并记录，防止污染向量库（如元数据文件被误加载）
                skipped += 1
                continue
            current_ids.add(doc.doc_id)
            ids_batch.append(doc.doc_id)
            vectors_batch.append(emb.tolist())

        if skipped:
            GLOBAL_TRACKER.add_trace(
                stage="vector_db",
                label=f"跳过 {skipped} 条无有效 doc_id 的文档",
                content={}
            )

        stored_data = self.collection.get(include=[])
        stored_ids = set(stored_data["ids"])

        delete_ids = stored_ids - current_ids
        if delete_ids:
            GLOBAL_TRACKER.add_trace(
                stage="vector_db",
                label="删除库中已移除文件向量",
                content={"delete_count": len(delete_ids)}
            )
            self.collection.delete(ids=list(delete_ids))

        GLOBAL_TRACKER.add_trace(
            stage="vector_db",
            label="执行upsert同步",
            content={"doc_count": len(ids_batch)}
        )
        self.collection.upsert(
            ids=ids_batch,
            embeddings=vectors_batch,
        )
        GLOBAL_TRACKER.add_trace(
            stage="vector_db",
            label="向量库增量同步完成",
            content={"total_count": self.collection.count()}
        )

    def query(self, embedding, top_k):

        return self.collection.query(

            query_embeddings=[embedding.tolist()],

            n_results=top_k

        )
