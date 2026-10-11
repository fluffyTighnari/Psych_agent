from config.model_config import BASE_DIR

DATA_DIR = BASE_DIR / "data"

STORE_DIR = BASE_DIR / "store"

CONFIG_DIR = BASE_DIR / "config"

NOTES_DIR = DATA_DIR / "notes"

KNOWLEDGE_DIR = DATA_DIR / "knowledge"

VECTOR_DB_DIR = STORE_DIR / "vector_db"

BM25_PATH = STORE_DIR / "bm25_store" / "bm25"

ID_MAP_PATH = CONFIG_DIR / "id_map.json"

META_DB_PATH = STORE_DIR / "knowledge_meta.db"

MEMORY_DB_PATH = STORE_DIR / "session_memory.db"

COLLECTION_NAME = "psych_notes"

MEMORY_DIR = DATA_DIR / "memory"

MEMORY_VECTOR_DB_DIR = STORE_DIR / "memory_vector_db"

MEMORY_META_DB_PATH = STORE_DIR / "memory_meta.db"

MEMORY_COLLECTION_NAME = "psych_memories"

SESSION_DIR = STORE_DIR / "current_session.db"

