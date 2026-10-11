import sqlite3
from pathlib import Path
from typing import List, Optional

from core.schema import Memory


class MemoryMetaDB:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_table()

    def _get_conn(self):
        """获取数据库连接：WAL 模式 + busy_timeout，避免并发写锁库"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_table(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        create_sql = """
        CREATE TABLE IF NOT EXISTS memory_meta (
            id TEXT PRIMARY KEY,
            start_time TEXT,
            end_time TEXT,
            title TEXT,
            summary TEXT,
            topics TEXT,
            keywords TEXT,
            primary_emotion TEXT,
            emotion_intensity REAL
        )
        """
        cursor.execute(create_sql)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_title ON memory_meta(title)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_topics ON memory_meta(topics)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_emotion ON memory_meta(primary_emotion)")
        conn.commit()
        conn.close()

    def upsert(self, memory: Memory):
        conn = self._get_conn()
        cursor = conn.cursor()
        sql = """
        INSERT INTO memory_meta
        (id, start_time, end_time, title, summary, topics, keywords, primary_emotion, emotion_intensity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            start_time=excluded.start_time,
            end_time=excluded.end_time,
            title=excluded.title,
            summary=excluded.summary,
            topics=excluded.topics,
            keywords=excluded.keywords,
            primary_emotion=excluded.primary_emotion,
            emotion_intensity=excluded.emotion_intensity
        """
        data = (
            memory.id,
            memory.start_time,
            memory.end_time,
            memory.title,
            memory.summary,
            ",".join(memory.topics),
            ",".join(memory.keywords),
            memory.emotion.get("primary", ""),
            memory.emotion.get("intensity", 0.0),
        )
        cursor.execute(sql, data)
        conn.commit()
        conn.close()

    def filter_memories(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        topic_like: Optional[List[str]] = None,
        keyword_like: Optional[List[str]] = None,
        primary_emotion: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[str]:
        conn = self._get_conn()
        cursor = conn.cursor()
        conditions = []
        params = []

        if start_date and end_date:
            conditions.append("start_time BETWEEN ? AND ?")
            params.extend([start_date, end_date])
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
            conditions.append(f"primary_emotion IN ({placeholders})")
            params.extend(primary_emotion)

        where_sql = "WHERE " + " AND ".join(conditions) if conditions else ""
        limit_sql = f"LIMIT {limit}" if limit else ""
        full_sql = f"SELECT id FROM memory_meta {where_sql} {limit_sql}"

        cursor.execute(full_sql, params)
        rows = cursor.fetchall()
        conn.close()
        return [row["id"] for row in rows]
