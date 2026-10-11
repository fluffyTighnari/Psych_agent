import json
import re
import os
from datetime import datetime
from typing import List, Dict, Optional

from config.path_config import MEMORY_DIR
from config.prompt_config import session_summarizer_prompt
from config.topic_config import VALID_TOPICS
from core.schema import create_memory, Memory
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.helper.json_extract import safe_load_json


class SessionSummarizer:
    """将一段完整心理咨询对话总结为结构化 Memory 对象，持久化到 MEMORY_DIR。"""

    def __init__(self, model):
        self.model = model

    def _build_summary_prompt(self, dialogues_text: str) -> List[Dict]:
        system_content = session_summarizer_prompt
        messages = [
            {"role": "system", "content": system_content.strip()},
            {"role": "user", "content": f"对话记录：\n{dialogues_text}"}
        ]
        return messages

    def _parse_response(self, raw_text: str) -> Optional[dict]:
        data = safe_load_json(raw_text)
        if data is None:
            GLOBAL_TRACKER.add_trace(
                stage="summarize_memory",
                label="Memory JSON解析失败",
                content={"error": "未找到完整JSON或解析失败"},
                is_error=True,
                error_msg="未找到完整JSON或解析失败"
            )
            return None
        try:
            for k in ("title", "summary", "topics", "keywords", "emotion", "insights"):
                if k not in data:
                    return None
            if not isinstance(data["emotion"], dict):
                data["emotion"] = {"primary": "Neutral", "secondary": "", "intensity": 0.0}
            data["emotion"].setdefault("primary", "Neutral")
            data["emotion"].setdefault("intensity", 0.0)
            data["topics"] = [t for t in data.get("topics", []) if t in VALID_TOPICS][:3]
            return data
        except (TypeError, ValueError) as e:
            GLOBAL_TRACKER.add_trace(
                stage="summarize_memory",
                label="Memory JSON字段校验失败",
                content={"error": str(e)},
                is_error=True,
                error_msg=str(e)
            )
            return None

    @staticmethod
    def _dialogues_to_text(dialogues: List[Dict]) -> str:
        lines = []
        for d in dialogues:
            role = "用户" if d.get("role") == "user" else "助手"
            lines.append(f"{role}：{d.get('content', '')}")
        return "\n".join(lines)

    @staticmethod
    def _write_memory_json(memory: Memory) -> str:
        """将 Memory 序列化写入 data/memory/{id}.json，返回文件路径。"""
        os.makedirs(MEMORY_DIR, exist_ok=True)
        json_path = MEMORY_DIR / f"{memory.id}.json"
        memory_dict = {
            "id": memory.id,
            "start_time": memory.start_time,
            "end_time": memory.end_time,
            "title": memory.title,
            "summary": memory.summary,
            "topics": memory.topics,
            "keywords": memory.keywords,
            "emotion": memory.emotion,
            "dialogues": memory.dialogues,
            "insights": memory.insights,
            "referenced_documents": memory.referenced_documents,
            "related_memory": memory.related_memory,
            "guided_reasons": memory.guided_reasons,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(memory_dict, f, ensure_ascii=False, indent=2)
        return str(json_path)

    def summarize(
        self,
        session_id: str,
        chat_history: List[Dict],
        referenced_documents: Optional[List[str]] = None,
        guided_reasons: Optional[List[Dict]] = None,
    ) -> Optional[Memory]:
        """
        :param session_id: 会话唯一标识
        :param chat_history: 完整对话列表 [{"role":"user/assistant","content":"..."}]
        :param referenced_documents: 本次会话引用的文档ID列表
        :param guided_reasons: 本次会话的引导推理问答链
        :return: Memory 对象，失败返回 None
        """
        if not chat_history:
            GLOBAL_TRACKER.add_trace(
                stage="summarize_memory",
                label="chat_history为空，跳过总结",
                content={}
            )
            return None

        dialogues_text = self._dialogues_to_text(chat_history)
        messages = self._build_summary_prompt(dialogues_text)
        raw_response = self.model.chat(messages=messages)
        GLOBAL_TRACKER.add_trace(
            stage="summarize_memory",
            label="Memory总结模型原始输出",
            content={"raw_response": raw_response[:500]}
        )

        parsed = self._parse_response(raw_response)
        if parsed is None:
            raw_response = self.model.chat(messages=messages)
            parsed = self._parse_response(raw_response)
        if parsed is None:
            GLOBAL_TRACKER.add_trace(
                stage="summarize_memory",
                label="Memory总结解析两次均失败",
                content={},
                is_error=True,
                error_msg="两次解析均失败"
            )
            return None

        start_time = ""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M")

        memory = create_memory(
            mem_id=session_id,
            start_time=start_time or now,
            end_time=now,
            title=parsed["title"],
            summary=parsed["summary"],
            topics=parsed["topics"],
            keywords=parsed["keywords"],
            emotion=parsed["emotion"],
            dialogues=chat_history,
            insights=parsed["insights"],
            referenced_documents=referenced_documents or [],
            guided_reasons=guided_reasons or [],
        )

        json_path = self._write_memory_json(memory)

        GLOBAL_TRACKER.add_trace(
            stage="summarize_memory",
            label="Memory已持久化到磁盘",
            content={"path": json_path, "title": memory.title}
        )

        return memory
