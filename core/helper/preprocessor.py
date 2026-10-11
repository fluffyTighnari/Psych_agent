"""
Preprocessor:读取特定目录下文件，调用 self.model.chat 让模型输出指定格式的 json
"""
import os
import json
import re
from typing import List, Dict, Optional
import hashlib

from config.prompt_config import preprocessor_prompt
from core.helper.trace_tracker import GLOBAL_TRACKER
from core.helper.json_extract import safe_load_json

MULTI_NEWLINE_PAT = re.compile(r'\n{2,}')
LINE_TRIM_PAT = re.compile(r'^\s+|\s+$', flags=re.MULTILINE)
SECTION_PATTERN = re.compile(r'### (problem|analysis|solution)\s*\n([\s\S]*?)(?=### |$)', re.S)

class DocumentPreprocessor:
    def __init__(self, model, output_root_dir: str):
        """
        :param model: ollama 封装模型实例，具备 .chat(messages)
        :param output_root_dir: 输出JSON文件的根目录
        """
        self.model = model
        self.output_root_dir = output_root_dir
        self.json_extract_pattern = re.compile(r"```json\s*([\s\S]*?)\s*```")

        self.folder_type_mapping = {
            "Daily_thoughts": "daily",
            "Weekly_thoughts": "weekly"
        }
        os.makedirs(self.output_root_dir, exist_ok=True)

    def generate_stable_doc_id(self, file_abs_path: str) -> str:
        """根据文件绝对路径生成固定不变的doc_id"""
        path_bytes = file_abs_path.strip().replace("\\", "/").lower().encode("utf-8")
        md5_val = hashlib.md5(path_bytes).hexdigest()
        return md5_val

    # ===== 增量处理 manifest：记录源文件 mtime/size 与对应 JSON =====
    def _manifest_path(self) -> str:
        return os.path.join(self.output_root_dir, ".preprocess_manifest.json")

    def _load_manifest(self) -> dict:
        try:
            with open(self._manifest_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_manifest(self, manifest: dict):
        try:
            with open(self._manifest_path(), "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except OSError:
            GLOBAL_TRACKER.add_trace(
                stage="preprocess",
                label="增量 manifest 写入失败（不影响本次处理）",
                content={"path": self._manifest_path()},
                is_error=True,
                error_msg="manifest 写入失败"
            )

    def extract_three_sections(self, text: str) -> dict:
        """从周记原文截取problem、analysis、solution，无匹配返回空字符串"""
        res = {"problem": "", "analysis": "", "solution": ""}
        matches = SECTION_PATTERN.findall(text)
        for name, content in matches:
            clean = content.replace("\t", "").replace("&#x09;", "")
            clean = LINE_TRIM_PAT.sub("", clean)
            clean = MULTI_NEWLINE_PAT.sub("\n", clean)
            clean = clean.strip()
            res[name] = clean
        return res

    def _extract_json_from_text(self, raw_text: str) -> Optional[dict]:
        data = safe_load_json(raw_text)
        if data is None:
            GLOBAL_TRACKER.add_trace(
                stage="preprocess",
                label="输出中未找到完整JSON大括号",
                content={},
                is_error=True,
                error_msg="输出中未找到完整JSON大括号"
            )
            return None
        try:
            required = ["summary", "topics", "keywords", "emotion"]
            for k in required:
                if k not in data:
                    raise ValueError(f"JSON缺失必填字段: {k}")
            if not isinstance(data["emotion"], dict):
                data["emotion"] = {"primary": "Neutral", "secondary": "", "intensity": 0.0}
            if "primary" not in data["emotion"]:
                data["emotion"]["primary"] = "Neutral"
            if "intensity" not in data["emotion"] or not isinstance(data["emotion"]["intensity"], float):
                data["emotion"]["intensity"] = 0.0
            if not isinstance(data["topics"], list):
                data["topics"] = []
            if not isinstance(data["keywords"], list):
                data["keywords"] = []
            return data
        except ValueError as ve:
            GLOBAL_TRACKER.add_trace(
                stage="preprocess",
                label="JSON字段校验失败",
                content={"error": str(ve)},
                is_error=True,
                error_msg=str(ve)
            )
            return None

    def _build_analysis_prompt(self, document_text: str) -> List[Dict]:
        system_content = preprocessor_prompt
        user_content = f"原文：\n{document_text}"
        messages = [
            {"role": "system", "content": system_content.strip()},
            {"role": "user", "content": user_content.strip()}
        ]
        return messages

    def analyze_document(self, doc_text: str, retry_times=1) -> Optional[dict]:
        messages = self._build_analysis_prompt(doc_text)
        raw_response = self.model.chat(messages=messages)
        GLOBAL_TRACKER.add_trace(
            stage="preprocess",
            label="模型原始输出",
            content={"raw_response": raw_response[:500]}
        )
        parsed = self._extract_json_from_text(raw_response)
        if parsed is None and retry_times > 0:
            GLOBAL_TRACKER.add_trace(
                stage="preprocess",
                label="解析失败，正在重试",
                content={}
            )
            raw_response = self.model.chat(messages=messages)
            parsed = self._extract_json_from_text(raw_response)
        return parsed

    def process_single_file(self, file_path: str, doc_type: str) -> Optional[dict]:
        filename = os.path.basename(file_path)
        json_filename = os.path.splitext(filename)[0] + ".json"
        if doc_type == "daily":
            target_json_path = os.path.join(self.output_root_dir, "Daily", json_filename)
        else:
            target_json_path = os.path.join(self.output_root_dir, "Weekly", json_filename)

        # ===== 增量判断：源文件 mtime+size 未变且 JSON 已存在 → 跳过 =====
        abs_src = os.path.abspath(file_path)
        abs_json = os.path.abspath(target_json_path)
        manifest = self._load_manifest()
        try:
            src_stat = os.stat(file_path)
        except OSError:
            src_stat = None
        entry = manifest.get(abs_src)

        if src_stat is not None and os.path.exists(target_json_path):
            if entry is None:
                # 存量数据：无 manifest 记录但 JSON 已存在，以当前源文件状态初始化（本次跳过，不重跑）
                manifest[abs_src] = {
                    "mtime": src_stat.st_mtime,
                    "size": src_stat.st_size,
                    "json": abs_json,
                }
                self._save_manifest(manifest)
                GLOBAL_TRACKER.add_trace(
                    stage="preprocess",
                    label="已存在处理结果（初始化增量记录），跳过",
                    content={"path": target_json_path}
                )
                return None
            if (entry.get("mtime") == src_stat.st_mtime
                    and entry.get("size") == src_stat.st_size
                    and entry.get("json") == abs_json):
                GLOBAL_TRACKER.add_trace(
                    stage="preprocess",
                    label="源文件未变更，跳过",
                    content={"path": target_json_path}
                )
                return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except Exception as e:
            GLOBAL_TRACKER.add_trace(
                stage="preprocess",
                label="文件读取失败",
                content={"path": file_path},
                is_error=True,
                error_msg=str(e)
            )
            return None
        if not content:
            return None

        if doc_type == "daily":
            # 先取无扩展名主干，再替换分隔符，避免把 ".md" 变成 "-md"
            stem = os.path.splitext(filename)[0]
            date_str = stem.replace(".", "-")
            title = date_str
            source = "experience"
        elif doc_type == "weekly":
            date_str = None
            title = filename
            source = "principle"
        else:
            GLOBAL_TRACKER.add_trace(
                stage="preprocess",
                label="未知文档类型",
                content={"doc_type": doc_type, "path": file_path},
                is_error=True,
                error_msg=f"未知类型 {doc_type}"
            )
            return None

        doc_id = self.generate_stable_doc_id(file_path)
        analysis_result = self.analyze_document(content)
        if analysis_result is None:
            GLOBAL_TRACKER.add_trace(
                stage="preprocess",
                label="模型JSON解析失败",
                content={"path": file_path},
                is_error=True,
                error_msg=f"模型JSON解析失败: {file_path}"
            )
            return None

        final_item = {
            "id": doc_id,
            "title": title,
            "type": doc_type,
            "date": date_str,
            "source": source,
            "word_count": len(content),
            "relative_path": file_path,
            "knowledge_path": target_json_path,
            "summary": analysis_result["summary"],
            "topics": analysis_result["topics"],
            "keywords": analysis_result["keywords"],
            "emotion": analysis_result["emotion"],
            "content": content,
        }
        if doc_type == "weekly":
            section_data = self.extract_three_sections(content)
            final_item["problem"] = section_data["problem"]
            final_item["analysis"] = section_data["analysis"]
            final_item["solution"] = section_data["solution"]

        try:
            os.makedirs(os.path.dirname(target_json_path), exist_ok=True)
            with open(target_json_path, "w", encoding="utf-8") as fw:
                json.dump(final_item, fw, ensure_ascii=False, indent=2)
            # 处理成功 → 更新增量 manifest
            if src_stat is not None:
                manifest[abs_src] = {
                    "mtime": src_stat.st_mtime,
                    "size": src_stat.st_size,
                    "json": abs_json,
                }
                self._save_manifest(manifest)
            GLOBAL_TRACKER.add_trace(
                stage="preprocess",
                label="JSON已写出",
                content={"path": target_json_path}
            )
        except Exception as e:
            GLOBAL_TRACKER.add_trace(
                stage="preprocess",
                label="写入文件失败",
                content={"path": target_json_path},
                is_error=True,
                error_msg=str(e)
            )
            return None
        return final_item

    def _scan_target_folder(self, folder_path: str, doc_type: str, suffix: str):
        results = []
        for entry in os.scandir(folder_path):
            if entry.is_file() and entry.name.endswith(suffix):
                item = self.process_single_file(entry.path, doc_type)
                if item:
                    results.append(item)
            elif entry.is_dir():
                sub_items = self._scan_target_folder(entry.path, doc_type, suffix)
                results.extend(sub_items)
        return results

    def preprocess(self, root_dir: str, suffix: str = ".md") -> List[dict]:
        """
        递归扫描源根目录，找到Daily_thoughts / Weekly_thoughts
        """
        output_list = []

        for entry in os.scandir(root_dir):
            if entry.is_dir():
                folder_name = entry.name
                if folder_name in self.folder_type_mapping:
                    target_type = self.folder_type_mapping[folder_name]
                    sub_results = self._scan_target_folder(entry.path, target_type, suffix)
                    output_list.extend(sub_results)
                else:
                    deeper = self.preprocess(entry.path, suffix)
                    output_list.extend(deeper)
        return output_list
