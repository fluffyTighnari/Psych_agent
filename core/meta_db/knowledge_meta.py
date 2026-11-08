import re
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional, Any

from core.schema import Document
from core.helper.trace_tracker import GLOBAL_TRACKER

_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def _normalize_date(value):
    """把 2026-7-11 规范成 2026-07-11；无法识别的格式原样返回。

    日期以 TEXT 存储并参与 SQL 字符串比较，不补零会导致跨月误判
    （例如 '2026-10-01' < '2026-9-01'）。
    """
    if not value:
        return value
    m = _DATE_RE.match(str(value).strip())
    if not m:
        return value
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


class KnowledgeMetaDB:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        # 自动创建存储目录
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_table()

    def _get_conn(self):
        """获取数据库连接：WAL 模式 + busy_timeout，避免并发写锁库"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        conn.row_factory = sqlite3.Row  # 查询结果可以按key取值
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_table(self):
        """初始化数据表+索引"""
        conn = self._get_conn()
        cursor = conn.cursor()

        # 元数据表
        create_sql = """
        CREATE TABLE IF NOT EXISTS knowledge_meta (
            doc_id TEXT PRIMARY KEY,
            doc_type TEXT NOT NULL,
            date TEXT,
            primary_emotion TEXT,
            secondary_emotion TEXT,
            emotion_intensity REAL,
            topics TEXT,
            keywords TEXT,
            word_count INTEGER
        )
        """
        cursor.execute(create_sql)

        # 建立索引，加速筛选
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON knowledge_meta(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_type ON knowledge_meta(doc_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emotion ON knowledge_meta(primary_emotion)")

        # 历史数据迁移：日期补零，保证日期区间比较正确
        self._normalize_stored_dates(cursor)

        conn.commit()
        conn.close()

    @staticmethod
    def _normalize_stored_dates(cursor):
        """把库中不补零的历史日期统一成 YYYY-MM-DD（幂等，无差异时不写库）。"""
        rows = cursor.execute(
            "SELECT doc_id, date FROM knowledge_meta WHERE date IS NOT NULL"
        ).fetchall()
        updates = []
        for row in rows:
            norm = _normalize_date(row["date"])
            if norm != row["date"]:
                updates.append((norm, row["doc_id"]))
        if updates:
            cursor.executemany(
                "UPDATE knowledge_meta SET date = ? WHERE doc_id = ?", updates
            )
            GLOBAL_TRACKER.add_trace(
                stage="meta_db",
                label="日期格式规范化",
                content={"updated": len(updates)}
            )

    def insert_or_update(self, doc_meta: Dict[str, Any]):
        """单条：存在则更新，不存在插入"""
        conn = self._get_conn()
        cursor = conn.cursor()
        sql = """
        INSERT INTO knowledge_meta 
        (doc_id, doc_type, date, primary_emotion, secondary_emotion, emotion_intensity, topics, keywords, word_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(doc_id) DO UPDATE SET
            doc_type=excluded.doc_type,
            date=excluded.date,
            primary_emotion=excluded.primary_emotion,
            secondary_emotion=excluded.secondary_emotion,
            emotion_intensity=excluded.emotion_intensity,
            topics=excluded.topics,
            keywords=excluded.keywords,
            word_count=excluded.word_count
        """
        data = (
            doc_meta["doc_id"],
            doc_meta["doc_type"],
            _normalize_date(doc_meta["date"]),
            doc_meta["primary_emotion"],
            doc_meta["secondary_emotion"],
            doc_meta["emotion_intensity"],
            ",".join(doc_meta["topics"]),
            ",".join(doc_meta["keywords"]),
            doc_meta["word_count"]
        )
        cursor.execute(sql, data)
        conn.commit()
        conn.close()

    def batch_upsert(self, documents: List[Document]):
        """
        全量同步：新增/更新传入文档，删除库中不在本次列表的旧记录
        """
        if not documents:
            # 传入空列表，清空整张表
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM knowledge_meta;")
            conn.commit()
            conn.close()
            return

        conn = self._get_conn()
        cursor = conn.cursor()

        # 1. 获取本次所有文档id集合
        current_doc_ids = {doc.doc_id for doc in documents}

        # 2. 查询数据库全部现存id
        cursor.execute("SELECT doc_id FROM knowledge_meta;")
        db_all_ids = {row["doc_id"] for row in cursor.fetchall()}

        # 3. 找出需要删除的id：库存在，但本次不存在
        need_delete_ids = db_all_ids - current_doc_ids
        if need_delete_ids:
            placeholders = ",".join(["?"] * len(need_delete_ids))
            del_sql = f"DELETE FROM knowledge_meta WHERE doc_id IN ({placeholders})"
            cursor.execute(del_sql, tuple(need_delete_ids))
            GLOBAL_TRACKER.add_trace(
                stage="meta_db",
                label="清理废弃元数据",
                content={"delete_count": len(need_delete_ids)}
            )

        # 4. 批量插入/更新当前文档
        insert_sql = """
                     INSERT INTO knowledge_meta
                     (doc_id, doc_type, date, primary_emotion, secondary_emotion, emotion_intensity, topics, keywords, \
                      word_count)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(doc_id) DO \
                     UPDATE SET
                         doc_type=excluded.doc_type, \
                         date =excluded.date, \
                         primary_emotion=excluded.primary_emotion, \
                         secondary_emotion=excluded.secondary_emotion, \
                         emotion_intensity=excluded.emotion_intensity, \
                         topics=excluded.topics, \
                         keywords=excluded.keywords, \
                         word_count=excluded.word_count \
                     """
        batch_data = []
        for doc in documents:
            emotion = doc.emotion if isinstance(doc.emotion, dict) else {}
            topics = doc.topic if isinstance(doc.topic, list) else []
            keywords = doc.keywords if isinstance(doc.keywords, list) else []
            row = (
                doc.doc_id,
                doc.doc_type,
                _normalize_date(doc.date),
                emotion.get("primary"),
                emotion.get("secondary"),
                emotion.get("intensity"),
                ",".join(topics),
                ",".join(keywords),
                doc.word_count
            )
            batch_data.append(row)
        cursor.executemany(insert_sql, batch_data)

        conn.commit()
        conn.close()
        GLOBAL_TRACKER.add_trace(
            stage="meta_db",
            label="知识元数据批量同步完成",
            content={"upsert_count": len(batch_data)}
        )

    def delete_by_doc_id(self, doc_id: str):
        """删除单条（文件被删除时调用）"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM knowledge_meta WHERE doc_id = ?", (doc_id,))
        conn.commit()
        conn.close()

    def filter_meta(
        self,
        doc_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        topic_like: Optional[List[str]] = None,
        keyword_like: Optional[List[str]] = None,
        primary_emotion: Optional[List[str]] = None,
        limit: Optional[int] = None
    ) -> List[str]:
        """
        多条件筛选，返回匹配的doc_id列表。
        keyword_like: 关键词列表，AND 语义（每条都需命中）。
        primary_emotion: 情绪列表，OR 语义（主/次情绪命中其一即可）。
        """

        conn = self._get_conn()
        cursor = conn.cursor()
        conditions = []
        params = []
        if doc_type:
            conditions.append("doc_type = ?")
            params.append(doc_type)
        if start_date and end_date:
            conditions.append("date BETWEEN ? AND ?")
            params.extend([start_date, end_date])
        elif start_date:
            conditions.append("date >= ?")
            params.append(start_date)
        elif end_date:
            conditions.append("date <= ?")
            params.append(end_date)
        if topic_like:
            or_conds = []
            for t in topic_like:
                or_conds.append("topics LIKE ?")
                params.append(f"%{t}%")
            conditions.append("(" + " OR ".join(or_conds) + ")")
        if keyword_like:
            for kw in keyword_like:
                conditions.append("keywords LIKE ?")
                params.append(f"%{kw}%")
        if primary_emotion:
            placeholders = ",".join(["?"] * len(primary_emotion))
            conditions.append(
                f"(primary_emotion IN ({placeholders}) OR secondary_emotion IN ({placeholders}))"
            )
            params.extend(primary_emotion)
            params.extend(primary_emotion)

        where_sql = "WHERE " + " AND ".join(conditions) if conditions else ""
        limit_sql = f"LIMIT {limit}" if limit else ""
        full_sql = f"SELECT doc_id FROM knowledge_meta {where_sql} {limit_sql}"

        cursor.execute(full_sql, params)
        rows = cursor.fetchall()
        conn.close()
        return [row["doc_id"] for row in rows]

