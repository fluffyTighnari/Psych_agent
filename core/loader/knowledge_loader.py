import json
from pathlib import Path

from core.schema import create_document
from config.path_config import ID_MAP_PATH
from core.helper.trace_tracker import current_tracker


class KnowledgeLoader:
    def __init__(self):
        # id_map.json 缺失，或其中记录的绝对路径在本机不可用（跨平台/换机器/迁移目录后常见），
        # 都视为过期 → 就地重建，否则 load_knowledge() 会静默返回空列表，检索链路直接失效。
        if not ID_MAP_PATH.exists() or not self._paths_usable():
            self._rebuild_id_map()
        with open(ID_MAP_PATH, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

    @staticmethod
    def _paths_usable() -> bool:
        """校验 id_map 中记录的路径是否至少有一条在本机存在（全不可用即判定为过期）。"""
        try:
            with open(ID_MAP_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(data, dict) or not data:
            return False
        return any(Path(str(path)).exists() for path in data.values())

    def _rebuild_id_map(self):
        """id_map.json 缺失或过期时，基于 knowledge 目录重建 id -> 绝对路径 映射。"""
        from config.path_config import KNOWLEDGE_DIR
        id_map = {}
        for file in KNOWLEDGE_DIR.rglob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            doc_id = data.get("id", "")
            if doc_id:
                id_map[doc_id] = str(file)
        ID_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ID_MAP_PATH, "w", encoding="utf-8") as f:
            json.dump(id_map, f, ensure_ascii=False, indent=2)
        current_tracker().add_trace(
            stage="knowledge_load",
            label="ID映射表已自动重建",
            content={"total_entries": len(id_map)},
        )

    def load_knowledge(self, ids: list[str]):
        knowledge = []
        for id in ids:
            path = self.data.get(id)
            if path is None:
                # id 不在映射表中（新增文档未重建索引等）：跳过并记录，避免 KeyError 打断整条检索链路
                current_tracker().add_trace(
                    stage="knowledge_load",
                    label="doc_id 不在 ID 映射表中，已跳过",
                    content={"doc_id": str(id)},
                    is_error=True,
                    error_msg="id_map.json 中无此 doc_id，请重建索引",
                )
                continue
            doc = self.load_document(path)
            if doc is None:
                continue
            knowledge.append(doc)

        return knowledge

    def load_document(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                doc_id = data.get("id", "")
                title = data.get("title", "")
                doc_type = data.get("type", "daily")
                date = data.get("date", "")
                source = data.get("source", "")
                word_count = len(data.get("content", ""))
                relative_path = data.get("relative_path", "")
                knowledge_path = data.get("knowledge_path", "")
                summary = data.get("summary", "")
                topics = data.get("topics", [])
                keywords = data.get("keywords", [])
                emotion = data.get("emotion", {})
                content = data.get("content", "")
                problem = data.get("problem", "")
                analysis = data.get("analysis", "")
                solution = data.get("solution", "")

                return create_document(
                    doc_id=doc_id,
                    content=content,
                    title=title,
                    source=source,
                    doc_type=doc_type,
                    relative_path=relative_path,
                    knowledge_path=knowledge_path,
                    summary=summary,
                    topic=topics,
                    keywords=keywords,
                    emotion=emotion,
                    problem=problem,
                    analysis=analysis,
                    solution=solution,
                    date=date,
                    word_count=word_count,
                )

        except json.JSONDecodeError as e:
            current_tracker().add_trace(
                stage="knowledge_load",
                label="JSON格式损坏",
                content={"path": str(path)},
                is_error=True,
                error_msg=str(e)
            )
            return None
        except FileNotFoundError:
            current_tracker().add_trace(
                stage="knowledge_load",
                label="文件不存在",
                content={"path": str(path)},
                is_error=True,
                error_msg="文件不存在"
            )
            return None
