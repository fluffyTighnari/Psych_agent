import pickle
import jieba
from pathlib import Path
from rank_bm25 import BM25Okapi

from core.helper.trace_tracker import current_tracker

STOP_WORDS = {"的", "了", "我", "你", "他", "是", "有", "和", "就", "都", "也", "很"}

# 富索引场景下的中文停用词（只在字段权重模式 field_weights 非空时生效）。
# 目的：把「任何文档都会出现」的功能词挡在词表之外，避免它们在 31 篇小语料上
# 拿到被 rank_bm25 抬到 eps*avg_idf 的伪正分，从而淹没真正有区分度的词项。
RICH_STOP_WORDS = STOP_WORDS | {
    "我们", "你们", "他们", "自己", "这个", "那个", "什么", "怎么", "可以", "因为",
    "所以", "但是", "而且", "如果", "就是", "不是", "没有", "一个", "一些", "这样",
    "那样", "时候", "现在", "还是", "或者", "并且", "然后", "其实", "已经", "觉得",
    "感觉", "知道", "应该", "需要", "可能", "一直", "非常", "真的", "这种", "那种",
    "并不", "也会", "而是", "不会", "能够", "对于", "关于", "以及", "同时", "只是",
    "起来", "出来", "过来", "下来", "上去", "下去", "一下", "一点", "有点", "很多",
    "更多", "更", "再", "又", "还", "让", "把", "被", "给", "对", "从", "到", "在",
}

# 权重缩放：外部传的相对权重会被乘以该系数后取整，用「词项重复次数」实现字段加权。
# 取 2 是为了让 0.5 这种半档权重也能被表达（0.5*2=1 次）。
WEIGHT_SCALE = 2

# 富索引默认字段权重（相对值）。这是「全局最优」调参后的默认值，
# 由 scripts/rag_opt/precompute.py 的网格搜索给出。
DEFAULT_FIELD_WEIGHTS = {
    "topic": 3.0,      # LLM 抽取的主题标签：语义聚合强，但区分度低 → 中等权重
    "keyword": 2.0,    # LLM 抽取的关键词：外部构造中最具特异性的部分 → 高权重
    "title": 3.0,      # 标题往往是全文最凝练的主题表述 → 高权重
    "summary": 2.0,    # LLM 摘要：凝练但含较多泛化词
    "problem": 2.0,    # 周记 problem：用户自己写的问题定义，与口语化提问同构
    "solution": 2.0,   # 周记 solution：真正「有效」的答案所在
    "analysis": 1.0,   # 周记 analysis：铺垫较长，权重最低
    "content": 1.0,    # 原文正文：词频真实、长度归一化才有意义
}


class BM25TagIndexer:
    def __init__(self, documents, bm25_path: str, topic_weight=3, keyword_weight=1,
                 field_weights: dict | None = None, k1: float = 1.5, b: float = 0.75,
                 min_len: int = 2, stop_words: set | None = None):
        """
        :param documents: list of Document对象
            - 传入非空列表：代表知识库有文档变更/新增，自动重建BM25索引覆盖本地文件
            - 传入空列表 []：仅读取本地已有索引，用于纯检索场景
        :param bm25_path: BM25索引持久化文件完整路径
        :param topic_weight: topics字段重复加权倍数（field_weights 为 None 时的兼容路径）
        :param keyword_weight: keywords字段重复加权倍数（field_weights 为 None 时的兼容路径）
        :param field_weights: 富索引字段权重表，如
            {"topic":3,"keyword":2,"title":3,"summary":2,"problem":2,"solution":2,"analysis":1,"content":1}
            非 None 时启用富索引：把标题/摘要/周记三段/正文一起纳入索引文档，
            使 BM25 的词频与长度归一化作用在「真实文本」上，而不是 LLM 抽取产物上。
        :param k1: BM25 词频饱和参数
        :param b: BM25 长度归一化强度（0=不归一化，1=完全归一化）
        :param min_len: 索引词项最小字符数（过滤单字噪声）
        :param stop_words: 自定义停用词集合；None 时按是否启用富索引自动选择
        """
        self.documents = documents
        self.bm25_path = Path(bm25_path)
        self.topic_weight = topic_weight
        self.keyword_weight = keyword_weight
        self.k1 = float(k1)
        self.b = float(b)
        self.min_len = int(min_len)
        self.field_weights = None if field_weights is None else {k: float(v) for k, v in field_weights.items()}
        if stop_words is not None:
            self.stop_words = set(stop_words)
        elif self.field_weights is not None:
            self.stop_words = set(RICH_STOP_WORDS)
        else:
            self.stop_words = set(STOP_WORDS)

        self.bm25: BM25Okapi | None = None
        self.corpus_tokenized: list[list[str]] = []
        self.doc_id_list: list[str] = []
        self.index_spec: dict = {}

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

    # ---------- 分词 / 字段加权 ----------

    def _cut(self, text: str) -> list[str]:
        """中文文本 → 词项：jieba 切分，去单字与停用词。"""
        if not text:
            return []
        out = []
        for w in jieba.cut(str(text)):
            w = w.strip().lower()
            if len(w) < self.min_len or w in self.stop_words:
                continue
            out.append(w)
        return out

    @staticmethod
    def _repeat(tokens: list[str], weight: float) -> list[str]:
        """按相对权重重复词项，用重复次数实现字段加权（BM25 对 query/doc 词频是线性的）。"""
        if not tokens or weight <= 0:
            return []
        n = max(1, int(round(weight * WEIGHT_SCALE)))
        return tokens * n

    def _legacy_tokens(self, doc) -> list[str]:
        """原始（v1）索引文档：topics ×3 + keywords ×1，保留完全一致的行为。"""
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

    def _rich_tokens(self, doc) -> list[str]:
        """富索引文档：把「外部构造产物」与「原文真实文本」都放进同一个索引文档。

        设计动机（对应优化要点）：
        1. 词频真实：原文里的词频差异不再被压缩成一次出现；
        2. 长度归一化有意义：分母是真实文本长度，长文（周记）不再凭空吃亏；
        3. 特异性可控：字段权重决定哪些构造产物被放大、哪些只是补充。
        """
        tokens: list[str] = []
        for field, weight in self.field_weights.items():
            if field == "topic":
                topics = doc.topic if isinstance(doc.topic, list) else []
                raw = [str(t).strip().lower() for t in topics if str(t).strip()]
                tokens.extend(self._repeat(raw, weight))
            elif field == "keyword":
                kws = doc.keywords if isinstance(doc.keywords, list) else []
                cut = self._cut(" ".join(str(k) for k in kws))
                tokens.extend(self._repeat(cut, weight))
            else:
                text = getattr(doc, field, "") or ""
                tokens.extend(self._repeat(self._cut(text), weight))
        return tokens

    def _tokenize_doc(self, doc) -> list[str]:
        if self.field_weights is None:
            return self._legacy_tokens(doc)
        return self._rich_tokens(doc)

    # ---------- 构建 / 持久化 ----------

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

        self.bm25 = BM25Okapi(self.corpus_tokenized, k1=self.k1, b=self.b)
        self.index_spec = {
            "mode": "legacy" if self.field_weights is None else "rich",
            "field_weights": self.field_weights,
            "k1": self.k1,
            "b": self.b,
            "min_len": self.min_len,
        }

        dump_package = {
            "bm25_model": self.bm25,
            "doc_id_order": self.doc_id_list,
            "corpus_tokens": self.corpus_tokenized,
            # 新增：索引规格（旧版 pkl 无此键，_load_from_disk 已做兼容）
            "index_spec": self.index_spec,
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
                "vocab_size": len(self.bm25.idf),
                "index_mode": self.index_spec.get("mode"),
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
        self.index_spec = dump_package.get("index_spec") or {"mode": "legacy"}
        # 索引里烘焙了 k1/b，读取后同步到实例，便于调试面板展示真实生效值
        self.k1 = float(getattr(self.bm25, "k1", self.k1))
        self.b = float(getattr(self.bm25, "b", self.b))
        current_tracker().add_trace(
            stage="bm25_index",
            label="BM25索引加载成功",
            content={"doc_count": len(self.doc_id_list), "index_mode": self.index_spec.get("mode")}
        )

    # ---------- 检索 ----------

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

    def score_all(self, query_tokens: list[str]) -> list[tuple[str, float]]:
        """返回全部文档按分数降序的 (doc_id, score)，供调试/实验使用（不过滤 0 分）。"""
        if self.bm25 is None:
            raise RuntimeError("BM25索引未初始化，请检查索引文件或重新构建")
        scores = self.bm25.get_scores(query_tokens)
        pairs = sorted(
            ((self.doc_id_list[i], float(s)) for i, s in enumerate(scores)),
            key=lambda x: x[1], reverse=True,
        )
        return pairs
