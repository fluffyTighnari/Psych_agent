"""修复已预处理数据中的 title 后缀问题。

背景：`preprocessor.py` 的 weekly 分支曾直接把文件名当 title（含 ".md"），
导致 13 篇周记的 title 变成「选择与价值.md」这类形式并泄漏到前端。
源码已修，但已生成的 data/knowledge/Weekly/*.json 仍是脏数据。

本脚本做两件事：
  1. 去掉 title 末尾的 ".md"
  2. 同步修正知识库 SQLite（网页展示读的是 DB，不是 JSON 文件）

用法：
    python scripts/fix_weekly_title_suffix.py           # 预览（不写入）
    python scripts/fix_weekly_title_suffix.py --apply   # 实际写入
"""
import json
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "data" / "knowledge"
META_DB_PATH = None

# 复用项目路径配置，避免硬编码
sys.path.insert(0, str(BASE_DIR))
try:
    from config.path_config import META_DB_PATH as _META  # type: ignore
    META_DB_PATH = _META
except Exception:
    pass


def fix_json_files(apply: bool) -> int:
    """修正 Weekly json 里的 title。返回修正条数。"""
    fixed = 0
    for f in sorted((KNOWLEDGE_DIR / "Weekly").glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [skip] {f.name}: 读取失败 {e}")
            continue

        title = str(data.get("title") or "")
        if not title.endswith(".md"):
            continue

        new_title = title[:-3].rstrip()
        print(f"  {f.name}")
        print(f"    - {title!r}")
        print(f"    + {new_title!r}")

        if apply:
            data["title"] = new_title
            f.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        fixed += 1
    return fixed


def fix_meta_db(apply: bool) -> int:
    """检查知识库 SQLite 是否也存了 title。

    实测表 `knowledge_meta` 只有 doc_id / doc_type / date / 情绪 / topics /
    keywords / word_count，**没有 title 列** —— 网页展示的标题来自
    KNOWLEDGE_CACHE（读 data/knowledge/**/*.json）。所以修 JSON 即可，
    这里只做一次结构确认，避免误以为漏改。
    """
    if META_DB_PATH is None:
        print("  [skip] 未找到 META_DB_PATH 配置")
        return 0

    db_path = Path(META_DB_PATH)
    if not db_path.exists():
        print(f"  [skip] 数据库不存在: {db_path}")
        return 0

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        tables = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        has_title = False
        for t in tables:
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
            if "title" in cols:
                has_title = True
                print(f"  注意：{t} 表含 title 列，需确认是否也要修")
        if not has_title:
            print("  确认：SQLite 不存 title，标题由 JSON + KNOWLEDGE_CACHE 提供，无需修库")
        return 0
    finally:
        conn.close()


def main() -> None:
    apply = "--apply" in sys.argv
    mode = "【实际写入】" if apply else "【预览模式，不写入】"
    print(f"修复 weekly title 的 .md 后缀 {mode}\n")

    print("=== 1. JSON 文件 ===")
    n_json = fix_json_files(apply)
    print(f"共 {n_json} 个文件待修\n")

    print("=== 2. 知识库 SQLite ===")
    n_db = fix_meta_db(apply)
    print(f"共 {n_db} 条记录待修\n")

    if not apply and (n_json or n_db):
        print("确认无误后执行：python scripts/fix_weekly_title_suffix.py --apply")


if __name__ == "__main__":
    main()
