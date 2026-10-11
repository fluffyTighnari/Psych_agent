import json
from pathlib import Path

from core.schema import create_memory
from config.path_config import MEMORY_DIR
from core.helper.trace_tracker import GLOBAL_TRACKER


class MemoryLoader:
    def __init__(self):
        self.memory_dir = MEMORY_DIR
        self.memories = []

    def load_memories(self):
        self.memories.clear()
        if not self.memory_dir.exists():
            return []
        for file in self.memory_dir.rglob("*.json"):
            m = self.load_memory(file)
            if m:
                self.memories.append(m)
        return self.memories

    @staticmethod
    def load_memory(path: Path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return create_memory(
                    mem_id=data.get("id", ""),
                    start_time=data.get("start_time", ""),
                    end_time=data.get("end_time", ""),
                    title=data.get("title", ""),
                    summary=data.get("summary", ""),
                    topics=data.get("topics", []),
                    keywords=data.get("keywords", []),
                    emotion=data.get("emotion", {}),
                    dialogues=data.get("dialogues", []),
                    insights=data.get("insights", []),
                    referenced_documents=data.get("referenced_documents", []),
                    related_memory=data.get("related_memory", []),
                    guided_reasons=data.get("guided_reasons", []),
                )
        except (json.JSONDecodeError, FileNotFoundError) as e:
            GLOBAL_TRACKER.add_trace(
                stage="memory_load",
                label="加载memory失败",
                content={"path": str(path)},
                is_error=True,
                error_msg=str(e)
            )
            return None
