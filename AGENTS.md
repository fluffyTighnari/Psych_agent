# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Environment & Commands

- Python virtual environment is in `.venv/`. Activate with `.venv/Scripts/activate` (Windows) before running anything.
- Install dependencies: `pip install -r requirements.txt`
- Run the main chat loop: `python main.py`
- Run the full preprocessing pipeline: `python preprocess.py`
- Test individual components (e.g. prompt optimizer): `python test.py`
- The `.env` file at project root stores `DEEPSEEK_API_KEY` and `DEEPSEEK_BASE_URL`.

## Architecture Overview

This is a **psychological counseling RAG system** that retrieves the user's own past journal entries, synthesized principles, and historical session memories to generate personalized counseling responses. It uses a **two-tier LLM setup**: DeepSeek API for agent routing and final RAG generation, and local Ollama models for preprocessing, query optimization, and session summarization.

### Data Pipeline (`preprocess.py`)

1. `DocumentPreprocessor` scans raw `.md` files from `data/notes/Daily_thoughts/` and `data/notes/Weekly_thoughts/`, calls a **local Ollama model** to extract structured JSON (summary, topics, keywords, emotion), and writes `.json` to `data/knowledge/Daily/` and `data/knowledge/Weekly/`. Weekly notes additionally have `problem`/`analysis`/`solution` sections parsed from markdown headers via regex.
2. `DocumentLoader` reads all `.json` from `data/knowledge/` into `Document` objects.
3. `KnowledgeMetaDB` (SQLite) stores document metadata for filtered lookups.
4. `EmbeddingModel` (local `bge-small-zh-v1.5` via SentenceTransformer) encodes documents by summary.
5. `VectorDB` (ChromaDB) persists dense vectors with incremental `sync_all_documents` (upsert + delete stale).
6. `BM25TagIndexer` indexes **topics and keywords** (not full text), persisted via pickle.

### Retrieval Pipeline (`core/helper/retriever.py`)

`Retriever.retrieve()` orchestrates a multi-stage pipeline:

1. **Query optimization**: Local LLM rewrites the user query into `search_query`, `match_topics` (2-3 from a fixed set of 20), and `keywords` (1-3 Chinese). Results cached via `@lru_cache`.
2. **Dual-path retrieval** (parallel threads):
   - **Dense**: `EmbeddingModel.encode(search_query)` → `VectorDB.query()` → top-k doc IDs
   - **Sparse**: `jieba.cut(raw_query) + match_topics + keywords` → `BM25.search()` → top-k doc IDs
3. **RRF fusion**: Merges both result lists by weighted reciprocal rank scoring.
4. **Document loading**: Loads full `Document` objects from JSON via `KnowledgeLoader`.
5. **Reranking**: Cross-encoder (`bge-reranker-base`) scores each (query, doc_summary) pair, filters below threshold (0.3), returns top-k.

### Agent Router (Intent Classification)

`core/agent.py` is the main entry point (`agent_service_entry`). It uses **DeepSeek API** (`deepseek-v4-flash`) with LangChain's `create_openai_tools_agent` to route user input to one of 6 tools defined in `core/tools.py`:

1. **`meta_filter_tool`** — Fuzzy metadata filtering (by doc_type, date range, topic keyword, emotion).
2. **`precise_text_filter_tool`** — Exact text search within document content.
3. **`psychological_consult_tool`** — Full RAG counseling pipeline (lazily initializes a global `PsychRAGAgent` singleton).
4. **`search_memory_tool`** — Semantic search over historical session memories.
5. **`precise_memory_filter_tool`** — Metadata-based filtering of past session records.
6. **`summarize_memory_tool`** — Summarizes current conversation and persists as a `Memory`.

The router prompt in `config/prompt_config.py` (`agent_prompt`) strictly instructs the LLM to only route to tools and pass through tool output verbatim — no rewriting.

### Session & Memory System

- **`SingleSessionState`** (`core/meta_db/context_meta.py`): Persists current session state to SQLite (`store/current_session.db`), survives restarts. Tracks `full_chat_history`, `similar_memories`, `referenced_doc_ids`, and `last_consult_query`.
- **Topic continuity detection** (`check_topic_continuity`): When two consecutive psychological consult queries are about different topics, the old session is auto-summarized and archived, and a new session begins.
- **`SessionSummarizer`** (`core/helper/session_summarizer.py`): Uses a local Ollama model to summarize a full conversation into a structured `Memory` object (title, summary, topics, keywords, emotion, insights).
- **Memory persistence**: Each `Memory` is saved as JSON in `data/memory/`, indexed in `MemoryVectorDB` (ChromaDB) for semantic search, and registered in `MemoryMetaDB` (SQLite) for metadata filtering.

### Response Generation (`core/helper/RAG_agent.py`)

`PsychRAGAgent` formats retrieved documents into three knowledge streams in the prompt:

- **Memory**: Historical session summaries (highest priority — referenced first for continuity).
- **Principle** (weekly docs): Structured as Problem → Analysis → Solution, used as validated frameworks.
- **Experience** (daily docs): Full journal content with date and emotion, used only for empathetic resonance.

Generation uses **DeepSeek API** (`deepseek-v4-flash`). The prompt enforces: prioritize Principle for solutions, use Experience only for empathy, never fabricate experiences.

### Key Data Types (`core/schema.py`)

- **`Document`**: `doc_id`, `content`, `summary`, `doc_type` ("daily"/"weekly"), `topic` (English labels), `keywords` (Chinese), `emotion` (dict with primary/secondary/intensity). Weekly docs also have `problem`, `analysis`, `solution`.
- **`Memory`**: `id`, `start_time`, `end_time`, `title`, `summary`, `topics`, `keywords`, `emotion`, `dialogues`, `insights`, `referenced_documents`.
- **`Knowledge_context`**: Simplified view used for reranker input.

### Config (`config/`)

- **`model_config.py`**: Model names/paths — `LARGE_MODEL_NAME` (Ollama, default `qwen3.5:9b-128k`), `SMALL_MODEL_NAME` (Ollama, default `qwen2:1.5b`), `EMBEDDING_MODEL`, `RERANKING_MODEL`, DeepSeek API key/URL from `.env`.
- **`path_config.py`**: All data/store/config directory paths.
- **`prompt_config.py`**: All LLM prompts (optimizer, preprocessor, RAG system/human, session summarizer, agent router).
- **`topic_config.py`**: 20 standard psychological topics, each mapped to ~30 Chinese keywords. `search_topic(keyword)` does reverse lookup.

### Two LLM Tiers

| Purpose | Model | Runtime |
|---|---|---|
| Agent routing, RAG generation | DeepSeek API (`deepseek-v4-flash`) | `langchain_deepseek.ChatDeepSeek` |
| Preprocessing, query optimization, session summarization | Local Ollama (`qwen3.5:9b-128k` or `qwen2:1.5b`) | `core/llm.py` (wraps `ollama.chat`) |

Embedding and reranking use local models loaded via SentenceTransformer from `models/`.

### Web UI
