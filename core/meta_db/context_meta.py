import sqlite3
import json
import threading
from pathlib import Path
from dataclasses import asdict

from core.schema import Memory
from config.path_config import SESSION_DIR

# 会话持久化存储路径
SESSION_STORE_PATH = Path(SESSION_DIR)

def _get_conn():
    """统一会话库连接：WAL 模式 + busy_timeout，避免并发写锁库"""
    conn = sqlite3.connect(SESSION_STORE_PATH, check_same_thread=False, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

class SingleSessionState:
    def __init__(self):
        self.lock = threading.RLock()  # 会话读写并发锁：agent/tools/api 共享，同线程可重入
        self.session_id: str = ""
        self.full_chat_history: list[dict] = [] # 原始对话[{"role":"user","content":...}]
        self.similar_memories: list[Memory] = [] # 本轮匹配到的历史记忆
        self.referenced_doc_ids: set[str] = set() # RAG用到的文档id
        self.last_consult_query: str = ""
        self.guided_reasons: list[dict] = [] # 引导推理问答链 [{role:'guide'|'user', content}]
        self.last_role: str = "" # 上一条请求的角色，用于引导新链重置
        self.mode: str = "" # 会话模式："" 未选 / "direct" 直接咨询 / "guided" 引导咨询；首条锁定
        self.mode_problem: str = "" # guided 锚定的核心问题
        self.mode_situation: str = "" # guided 锚定的具体情境
        self.guided_ended: bool = False # 本轮引导是否已结束（【结束】后待新一轮）
        self.load_state()

    def init_session_db(self):
        """初始化单条会话存储表，只存当前唯一会话"""
        SESSION_STORE_PATH.parent.mkdir(exist_ok=True)
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS current_session (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            session_id TEXT,
            last_consult_query TEXT,
            full_chat_history TEXT, -- json数组字符串
            similar_mem TEXT, -- Memory对象json数组
            referenced_docs TEXT, -- 逗号分隔文档id
            guided_reasons TEXT, -- json数组字符串
            last_role TEXT,
            mode TEXT,
            mode_problem TEXT,
            mode_situation TEXT,
            guided_ended INTEGER
        )
        """)
        # 兼容旧库：列不存在时补加
        for col, typ in (("guided_reasons", "TEXT"), ("last_role", "TEXT"),
                         ("mode", "TEXT"), ("mode_problem", "TEXT"),
                         ("mode_situation", "TEXT"), ("guided_ended", "INTEGER")):
            try:
                cur.execute(f"ALTER TABLE current_session ADD COLUMN {col} {typ}")
            except Exception:
                pass
        conn.commit()
        conn.close()

    def save_state(self):
        """将当前会话dataclass存入sqlite，覆盖唯一一条记录"""
        with self.lock:
            conn = _get_conn()
            cur = conn.cursor()
            # Memory 序列化
            mem_json = json.dumps([asdict(m) for m in self.similar_memories], ensure_ascii=False)
            chat_json = json.dumps(self.full_chat_history, ensure_ascii=False)
            ref_str = ",".join(self.referenced_doc_ids)
            reasons_json = json.dumps(self.guided_reasons, ensure_ascii=False)
            data = (
                1,
                self.session_id,
                self.last_consult_query,
                chat_json,
                mem_json,
                ref_str,
                reasons_json,
                self.last_role,
                self.mode,
                self.mode_problem,
                self.mode_situation,
                1 if self.guided_ended else 0,
            )
            cur.execute("""
            INSERT OR REPLACE INTO current_session
            (id, session_id, last_consult_query, full_chat_history, similar_mem, referenced_docs, guided_reasons, last_role,
             mode, mode_problem, mode_situation, guided_ended)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, data)
            conn.commit()
            conn.close()

    def load_state(self):
        """从库加载上次会话，无数据返回全新空状态"""
        self.init_session_db()
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM current_session WHERE id=1")
        row = cur.fetchone()
        conn.close()
        if row is None:
            return
        # 反序列化（旧库缺列时以 None 兜底）
        cols = list(row) + [None, None, None, None, None, None]
        (_, sid, last_q, chat_str, mem_str, ref_str, reasons_str, last_role,
         mode, mode_problem, mode_situation, guided_ended) = cols[:12]
        chat_list = json.loads(chat_str) if chat_str else []
        mem_raw = json.loads(mem_str) if mem_str else []
        ref_set = set(ref_str.split(",")) if ref_str else set()
        reasons_list = json.loads(reasons_str) if reasons_str else []
        from core.schema import Memory
        mem_list = [Memory(**item) for item in mem_raw]

        self.session_id = sid
        self.last_consult_query = last_q
        self.full_chat_history = chat_list
        self.similar_memories = mem_list
        self.referenced_doc_ids = ref_set
        self.guided_reasons = reasons_list
        self.last_role = last_role or ""
        self.mode = mode or ""
        self.mode_problem = mode_problem or ""
        self.mode_situation = mode_situation or ""
        self.guided_ended = bool(guided_ended)


    def to_dict(self) -> dict:
        """导出可 JSON 序列化的会话状态视图：排除内部锁，Memory 对象转 dict。"""
        def _safe_mem(m):
            try:
                return asdict(m)
            except Exception:
                return m
        return {
            "session_id": self.session_id,
            "last_consult_query": self.last_consult_query,
            "last_role": self.last_role,
            "mode": self.mode,
            "mode_problem": self.mode_problem,
            "mode_situation": self.mode_situation,
            "guided_ended": self.guided_ended,
            "full_chat_history": self.full_chat_history,
            "similar_memories": [_safe_mem(m) for m in self.similar_memories],
            "referenced_doc_ids": sorted(self.referenced_doc_ids),
            "guided_reasons": self.guided_reasons,
        }

    def clear_all(self):
        """清空当前会话所有数据+数据库记录"""
        with self.lock:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM current_session WHERE id=1")
            conn.commit()
            conn.close()
            # 内存重置为空
            self.session_id = ""
            self.last_consult_query = ""
            self.full_chat_history = []
            self.similar_memories = []
            self.referenced_doc_ids = set()
            self.guided_reasons = []
            self.last_role = ""
            self.mode = ""
            self.mode_problem = ""
            self.mode_situation = ""
            self.guided_ended = False


SESSION_STATE = SingleSessionState()