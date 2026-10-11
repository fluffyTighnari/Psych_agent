from typing import Dict

from core.loader.memory_loader import MemoryLoader
from core.schema import Memory
from core.helper.trace_tracker import GLOBAL_TRACKER


class MemoryCache:
    def __init__(self, memories: list[Memory]):
        self.memories = memories
        self.cache: Dict[str, Memory] = {}
        self._load_all()

    def _load_all(self):
        """启动一次性加载所有json到内存"""
        for mem in self.memories:
            self.cache[mem.id] = mem

    def reload(self) -> list[Memory]:
        """重新从磁盘加载全部记忆并刷新缓存（新记忆持久化后调用，网页立即可见）。"""
        self.memories = memory_loader.load_memories()
        self.cache = {}
        self._load_all()
        GLOBAL_TRACKER.add_trace(
            stage="memory_cache",
            label="记忆缓存已重新加载",
            content={"memory_count": len(self.memories)}
        )
        return self.memories

    def get_by_ids(self, mem_ids: list[str]) -> list[Memory]:
        res = []
        for did in mem_ids:
            if did in self.cache:
                res.append(self.cache[did])
        return res

memory_loader = MemoryLoader()
MEMORY_CACHE = MemoryCache(memory_loader.load_memories())