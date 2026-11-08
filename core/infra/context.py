"""应用基础设施容器（AppContext）。

统一持有全部懒加载组件（记忆链路 / RAG / 引导 LLM / 分类 LLM / 知识元数据库），并提供
``rebuild()`` 作为模型配置变更后的**唯一**重建入口。

设计取舍：
- 重依赖组件（embedding / reranker / LLM / 向量库）首次访问才构造，import 期不加载。
- 构造逻辑物理收敛在本容器；``core/tools`` 旧 ``_get_memory_*`` / ``get_global_rag_agent``
  / ``_get_guide_llm`` 改为直接 ``get_app_context()`` 调用。
- 路由 Agent（``agent_executor``）因依赖 ``core.tools`` 的 @tool 包装，留在 ``core/agent.py``
  模块级构造，由 ``rebuild()`` 委托其 ``reset_llm_cache()`` 一并重建。
- 检索六组件（embedding/vector_db/bm25/prompt_optimizer/knowledge_loader/reranker）由
  ``core.helper.retrieval_pipeline`` 的进程级单例持有，``rebuild()`` 调其
  ``invalidate_retrieval_components()`` 失效（prompt_optimizer 绑定 small 模型，换模型必须重建）。
"""
import threading


class AppContext:
    def __init__(self):
        self._lock = threading.RLock()
        self._memory_embedding = None
        self._memory_vector_db = None
        self._memory_meta_db = None
        self._memory_summarizer = None
        self._guide_llm = None
        self._classify_llm = None
        self._rag_agent = None
        self._meta_db = None
        self.rebuild_count = 0

    # ---------- 记忆链路 ----------

    def memory_embedding(self):
        with self._lock:
            if self._memory_embedding is None:
                from config.model_config import EMBEDDING_MODEL
                from core.embedding.embedding_memory import MemoryEmbedding
                self._memory_embedding = MemoryEmbedding(EMBEDDING_MODEL)
            return self._memory_embedding

    def memory_vector_db(self):
        with self._lock:
            if self._memory_vector_db is None:
                from config.path_config import MEMORY_VECTOR_DB_DIR, MEMORY_COLLECTION_NAME
                from core.vector_db.memory_vector_db import MemoryVectorDB
                self._memory_vector_db = MemoryVectorDB(MEMORY_VECTOR_DB_DIR, MEMORY_COLLECTION_NAME)
            return self._memory_vector_db

    def memory_meta_db(self):
        with self._lock:
            if self._memory_meta_db is None:
                from config.path_config import MEMORY_META_DB_PATH
                from core.meta_db.memory_meta import MemoryMetaDB
                self._memory_meta_db = MemoryMetaDB(str(MEMORY_META_DB_PATH))
            return self._memory_meta_db

    def memory_summarizer(self):
        with self._lock:
            if self._memory_summarizer is None:
                from config.model_config import GLOBAL_MODEL
                from core.llm import LLM
                from core.helper.session_summarizer import SessionSummarizer
                self._memory_summarizer = SessionSummarizer(LLM(GLOBAL_MODEL.large))
            return self._memory_summarizer

    # ---------- 引导 LLM ----------

    def guide_llm(self):
        with self._lock:
            if self._guide_llm is None:
                from config.model_config import GLOBAL_MODEL
                from core.llm import LLM
                self._guide_llm = LLM(GLOBAL_MODEL.chat)
            return self._guide_llm

    # ---------- 意图分类小模型（阶段3：从 agent.py 模块级单例收编） ----------

    def classify_llm(self):
        with self._lock:
            if self._classify_llm is None:
                from config.model_config import GLOBAL_MODEL
                from core.llm import LLM
                self._classify_llm = LLM(GLOBAL_MODEL.small)
            return self._classify_llm

    # ---------- RAG ----------

    def rag_agent(self):
        with self._lock:
            if self._rag_agent is None:
                from core.helper.RAG_agent import PsychRAGAgent
                from core.helper.retrieval_pipeline import RetrievalPipeline, get_retrieval_components
                self._rag_agent = PsychRAGAgent(RetrievalPipeline(**get_retrieval_components()))
            return self._rag_agent

    # ---------- 知识元数据库（无模型依赖，构造一次即可） ----------

    def meta_db(self):
        with self._lock:
            if self._meta_db is None:
                from config.path_config import META_DB_PATH
                from core.meta_db.knowledge_meta import KnowledgeMetaDB
                self._meta_db = KnowledgeMetaDB(META_DB_PATH)
            return self._meta_db

    # ---------- 统一重建 ----------

    def rebuild(self) -> None:
        """模型配置更新后调用：清空本容器全部缓存，并委托其他模块重建其组件。"""
        with self._lock:
            self._memory_embedding = None
            self._memory_vector_db = None
            self._memory_meta_db = None
            self._memory_summarizer = None
            self._guide_llm = None
            self._classify_llm = None
            self._rag_agent = None
            # meta_db 无模型依赖，保留已构造实例不重建
            # 1) 检索组件单例（prompt_optimizer 绑定 small 模型，换 small 必须重建）
            from core.helper.retrieval_pipeline import invalidate_retrieval_components
            invalidate_retrieval_components()
            # 2) agent.py 路由 LLM / AgentExecutor
            from core.agent import reset_llm_cache as reset_agent_llm
            reset_agent_llm()
            self.rebuild_count += 1


_APP_CONTEXT = None
_APP_LOCK = threading.RLock()


def get_app_context() -> AppContext:
    global _APP_CONTEXT
    if _APP_CONTEXT is None:
        with _APP_LOCK:
            if _APP_CONTEXT is None:
                _APP_CONTEXT = AppContext()
    return _APP_CONTEXT


def rebuild_app() -> None:
    """便捷入口：模型配置更新后调用，统一重建全部组件。"""
    get_app_context().rebuild()
