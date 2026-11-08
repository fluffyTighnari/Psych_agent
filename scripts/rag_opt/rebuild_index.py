"""按 core/helper/retrieval_config.py 的索引规格重建 BM25 索引与向量库。

- 先备份现有产物到 store/_backup_<时间戳>/
- BM25：富索引（字段权重 + k1/b）
- 向量库：按 dense_doc_text(DENSE_DOC_VARIANT) 重新编码全部文档并增量同步

用法：
    python scripts/rag_opt/rebuild_index.py            # 备份 + 重建
    python scripts/rag_opt/rebuild_index.py --dry-run  # 只看将要做什么
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import os

os.chdir(ROOT)

from config.model_config import EMBEDDING_MODEL  # noqa: E402
from config.path_config import (  # noqa: E402
    BM25_PATH, COLLECTION_NAME, VECTOR_DB_DIR, STORE_DIR,
)
from core.embedding.embedding import EmbeddingModel  # noqa: E402
from core.helper.BM25 import BM25TagIndexer  # noqa: E402
from core.helper import retrieval_config as RC  # noqa: E402
from core.loader.document_loader import DocumentLoader  # noqa: E402
from core.vector_db.documents_vector_db import VectorDB  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--skip-vector", action="store_true")
    ap.add_argument("--skip-bm25", action="store_true")
    a = ap.parse_args()

    loader = DocumentLoader()
    docs = loader.load_documents()
    print(f"docs: {len(docs)}")
    print(f"BM25 field_weights: {RC.BM25_FIELD_WEIGHTS} k1={RC.BM25_K1} b={RC.BM25_B}")
    print(f"dense doc variant : {RC.DENSE_DOC_VARIANT}")
    if a.dry_run:
        return

    if not a.no_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = STORE_DIR / f"_backup_{stamp}"
        backup.mkdir(parents=True, exist_ok=True)
        if BM25_PATH.exists() and not a.skip_bm25:
            shutil.copy2(BM25_PATH, backup / "bm25")
            print(f"backed up bm25 -> {backup / 'bm25'}")
        if VECTOR_DB_DIR.exists() and not a.skip_vector:
            shutil.copytree(VECTOR_DB_DIR, backup / "vector_db", dirs_exist_ok=True)
            print(f"backed up vector_db -> {backup / 'vector_db'}")

    if not a.skip_bm25:
        t0 = time.time()
        idx = BM25TagIndexer(
            documents=docs,
            bm25_path=BM25_PATH,
            field_weights=RC.BM25_FIELD_WEIGHTS,
            k1=RC.BM25_K1,
            b=RC.BM25_B,
        )
        print(f"BM25 rebuilt in {time.time()-t0:.1f}s: avgdl={idx.bm25.avgdl:.1f} "
              f"vocab={len(idx.bm25.idf)} spec={idx.index_spec}")

    if not a.skip_vector:
        t0 = time.time()
        emb = EmbeddingModel(EMBEDDING_MODEL)
        vectors = emb.encode_documents(docs, variant=RC.DENSE_DOC_VARIANT)
        vdb = VectorDB(VECTOR_DB_DIR, COLLECTION_NAME)
        vdb.sync_all_documents(docs, vectors)
        print(f"vector db rebuilt in {time.time()-t0:.1f}s: count={vdb.count()}")


if __name__ == "__main__":
    main()
