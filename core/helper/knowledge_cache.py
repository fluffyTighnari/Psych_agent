from typing import Dict

from core.loader.document_loader import DocumentLoader
from core.schema import Document
from core.helper.trace_tracker import GLOBAL_TRACKER


class KnowledgeCache:
    def __init__(self, documents: list[Document]):
        self.documents = documents
        self.cache: Dict[str, Document] = {}
        self._load_all()

    def _load_all(self):
        """启动一次性加载所有json到内存"""
        for doc in self.documents:
            self.cache[doc.doc_id] = doc

    def reload(self) -> list[Document]:
        """重新从磁盘加载全部文档并刷新缓存（预处理/重建后调用，写入即生效）。"""
        self.documents = document_loader.load_documents()
        self.cache = {}
        self._load_all()
        GLOBAL_TRACKER.add_trace(
            stage="knowledge_cache",
            label="知识缓存已重新加载",
            content={"doc_count": len(self.documents)}
        )
        return self.documents

    def get_by_ids(self, doc_ids: list[str]) -> list[Document]:
        res = []
        for did in doc_ids:
            if did in self.cache:
                res.append(self.cache[did])
        return res

document_loader = DocumentLoader()
KNOWLEDGE_CACHE = KnowledgeCache(document_loader.load_documents())