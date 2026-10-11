import pickle
import jieba
from pathlib import Path
from rank_bm25 import BM25Okapi

from core.helper.trace_tracker import current_tracker

STOP_WORDS = {"的", "了", "我", "你", "他", "是", "有", "和", "就", "都", "也", "很"}

class BM25TagIndexer:
    def __init__(self, documents, bm25_path: str, topic_weight=3, keyword_weight=1):
        """
        :param documents: list of Document对象，包含 .topic / .keywords 属性
            - 传入非空列表：代表知识库有文档变更/新增，自动重建BM25索引覆盖本地文件
            - 传入空列表 []：仅读取本地已有索引，用于纯检索场景
        :param bm25_path: BM25索引持久化文件完整路径
        :param topic_weight: topics字段重复加权倍数
        :param keyword_weight: keywords字段重复加权倍数
        """
        self.documents = documents
        self.bm25_path = Path(bm25_path)
        self.topic_weight = topic_weight
        self.keyword_weight = keyword_weight

        self.bm25: BM25Okapi | None = None
        self.corpus_tokenized: list[list[str]] = []
        self.doc_id_list: list[str] = []

        if len(self.documents) == 0:
            if self.bm25_path.exists():
                self._load_from_disk()
            else:
                raise FileNotFoundError(f"无本地BM25索引文件：{self.bm25_path}，请先传入文档构建索引")
        else:
            self.build_index()

    @staticmethod
    def index_exists(bm25_path: str) -> bool:
        return Path(bm25_path).exists()

    def _tokenize_doc(self, doc) -> list[str]:
        topics = doc.topic if isinstance(doc.topic, list) else []
        raw_topics = [str(t).lower() for t in topics if t]
        topic_tokens = []
        for _ in range(self.topic_weight):
            topic_tokens.extend(raw_topics)

        keywords = doc.keywords if isinstance(doc.keywords, list) else []
        keyword_text = " ".join(str(k) for k in keywords)
        cut_words = list(jieba.cut(keyword_text))
        clean_words = [
            w for w in cut_words
            if len(w) > 1 and w not in STOP_WORDS
        ]
        keyword_tokens = []
        for _ in range(self.keyword_weight):
            keyword_tokens.extend(clean_words)

        return topic_tokens + keyword_tokens

    def build_index(self) -> BM25Okapi:
        """全量构建索引并写入磁盘持久化（自动覆盖旧索引）"""
        current_tracker().add_trace(
            stage="bm25_index",
            label="开始构建BM25索引",
            content={"path": str(self.bm25_path)}
        )
        self.corpus_tokenized.clear()
        self.doc_id_list.clear()

        for doc in self.documents:
            tokens = self._tokenize_doc(doc)
            self.corpus_tokenized.append(tokens)
            self.doc_id_list.append(doc.doc_id)

        current_tracker().add_trace(
            stage="bm25_index",
            label="BM25语料构建完成",
            content={"doc_count": len(self.corpus_tokenized)}
        )

        self.bm25 = BM25Okapi(self.corpus_tokenized)

        dump_package = {
            "bm25_model": self.bm25,
            "doc_id_order": self.doc_id_list,
            "corpus_tokens": self.corpus_tokenized
        }

        self.bm25_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.bm25_path, "wb") as f:
            pickle.dump(dump_package, f)

        current_tracker().add_trace(
            stage="bm25_index",
            label="BM25索引持久化完成",
            content={
                "path": str(self.bm25_path),
                "avgdl": round(self.bm25.avgdl, 2),
                "doc_count": len(self.bm25.doc_len),
                "vocab_size": len(self.bm25.idf)
            }
        )
        return self.bm25

    def _load_from_disk(self):
        """从本地pkl加载已有索引，恢复全部成员变量"""
        current_tracker().add_trace(
            stage="bm25_index",
            label="加载已有BM25索引",
            content={"path": str(self.bm25_path)}
        )
        with open(self.bm25_path, "rb") as f:
            dump_package = pickle.load(f)

        self.bm25 = dump_package["bm25_model"]
        self.doc_id_list = dump_package["doc_id_order"]
        self.corpus_tokenized = dump_package["corpus_tokens"]
        current_tracker().add_trace(
            stage="bm25_index",
            label="BM25索引加载成功",
            content={"doc_count": len(self.doc_id_list)}
        )

    def search(self, query_tokens: list[str], top_k: int = 3) -> list[str]:
        """
        BM25检索入口
        :param query_tokens: 预处理完成的查询分词列表（含扩充英文topic）
        :param top_k: 返回topN文档id
        :return: 按得分降序的doc_id列表（过滤0分文档）
        """
        if self.bm25 is None:
            raise RuntimeError("BM25索引未初始化，请检查索引文件或重新构建")

        scores = self.bm25.get_scores(query_tokens)
        ranked_pairs = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        hit_ids = []
        for idx, score in ranked_pairs:
            if score > 0 and len(hit_ids) < top_k:
                hit_ids.append(self.doc_id_list[idx])
        return hit_ids
