import json
from pathlib import Path

from core.schema import create_document
from config.path_config import KNOWLEDGE_DIR, ID_MAP_PATH
from core.helper.trace_tracker import GLOBAL_TRACKER


class DocumentLoader:

    def __init__(self):
        self.knowledge_dir = KNOWLEDGE_DIR
        self.documents = []

    def load_documents(self):
        self.documents.clear()  # 重置，避免重复加载（reload 场景翻倍）
        all_json_files = KNOWLEDGE_DIR.rglob("*.json")

        for file in all_json_files:
            # 跳过内部元数据/隐藏文件（如 .preprocess_manifest.json），防止被误当知识文档
            if file.name.startswith("."):
                continue
            doc = self.load_document(file)
            if doc is not None:  # 过滤加载失败的文档，避免 dict 混入下游触发 'dict' has no attribute
                self.documents.append(doc)

        return self.documents

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
                    summary = summary,
                    topic = topics,
                    keywords = keywords,
                    emotion = emotion,
                    problem = problem,
                    analysis = analysis,
                    solution = solution,
                    date=date,
                    word_count=word_count,
                )

        except json.JSONDecodeError as e:
            GLOBAL_TRACKER.add_trace(
                stage="document_load",
                label="JSON格式损坏",
                content={"path": str(path)},
                is_error=True,
                error_msg=str(e)
            )
            return None
        except FileNotFoundError:
            GLOBAL_TRACKER.add_trace(
                stage="document_load",
                label="文件不存在",
                content={"path": str(path)},
                is_error=True,
                error_msg="文件不存在"
            )
            return None

    def create_id_map(self):
        id_title_mapping = {}
        current_ids = set()
        for document in self.documents:
            doc_id = document.doc_id
            current_ids.add(doc_id)
            id_title_mapping[doc_id] = document.knowledge_path

        if ID_MAP_PATH.exists():
            with open(ID_MAP_PATH, "r", encoding="utf-8") as f:
                old_map = json.load(f)
            filtered_old = {k: v for k, v in old_map.items() if k in current_ids}
            filtered_old.update(id_title_mapping)
            id_title_mapping = filtered_old

        ID_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ID_MAP_PATH, "w", encoding="utf-8") as f:
            json.dump(id_title_mapping, f, ensure_ascii=False, indent=2)
        GLOBAL_TRACKER.add_trace(
            stage="document_load",
            label="ID映射表同步更新完成",
            content={"total_entries": len(id_title_mapping)}
        )
