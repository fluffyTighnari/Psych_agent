"""preprocess过程：
preprocessor统一预处理目录下所有文档，生成json文件
document_loader装载所有json文件
embedding_model构建所有知识向量
VectorDB更新知识库
BM25更新索引库"""
from config.model_config import GLOBAL_MODEL, EMBEDDING_MODEL
from config.path_config import KNOWLEDGE_DIR, DATA_DIR, VECTOR_DB_DIR, COLLECTION_NAME, BM25_PATH, META_DB_PATH
from core.helper.BM25 import BM25TagIndexer
from core.loader.document_loader import DocumentLoader
from core.embedding.embedding import EmbeddingModel
from core.meta_db.knowledge_meta import KnowledgeMetaDB
from core.vector_db.documents_vector_db import VectorDB
from core.llm import LLM
from core.helper.preprocessor import DocumentPreprocessor

model = LLM(
    GLOBAL_MODEL.large,
)

preprocessor = DocumentPreprocessor(
    model,
    KNOWLEDGE_DIR
)

preprocessor.preprocess(
    DATA_DIR
)
print("Preprocessor预处理完成")

loader = DocumentLoader()
all_docs = loader.load_documents()
loader.create_id_map()

print(f"DocumentLoader加载文件完成，一共加载 {len(all_docs)} 篇文档\n")

knowledge_db = KnowledgeMetaDB(
    META_DB_PATH
)
knowledge_db.batch_upsert(all_docs)

print(f"KnowledgeMetaDB更新数据库完成")

embedding_model = EmbeddingModel(EMBEDDING_MODEL)

embeddings = embedding_model.encode_documents(all_docs)

print("EmbeddingModel构建向量完成")

vector_db = VectorDB(
    VECTOR_DB_DIR,
    COLLECTION_NAME
)

vector_db.sync_all_documents(all_docs, embeddings)

print("VectorDB更新知识库完成")

indexer = BM25TagIndexer(
    documents=all_docs,
    bm25_path=BM25_PATH,
    topic_weight=3,
    keyword_weight=1
)

print("BM25TagIndexer更新索引库完成")

print("预处理部分已完成")