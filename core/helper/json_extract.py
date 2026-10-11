"""
JSON 宽松解析公共模块：统一 LLM 输出中提取结构化 JSON 的清洗逻辑。

此前 preprocessor / session_summarizer / prompt_optimizer 各自实现了一份
"去代码块 + 压缩空白 + 配对提取 + 解析"逻辑（三处拷贝，行为略有差异）。
此处收敛为唯一实现，各调用方仅保留字段级校验。
"""
import json
import re
from typing import Optional

_CODE_BLOCK_PAT = re.compile(r"```[a-zA-Z0-9]*\s*([\s\S]*?)\s*```")


def strip_code_blocks(text: str) -> str:
    """去除 ```lang ... ``` 代码块围栏，保留内部内容。"""
    return _CODE_BLOCK_PAT.sub(r"\1", text)


def normalize_json_text(text: str) -> str:
    """压缩空白/换行/全角空格，替换中文引号为英文引号。"""
    text = text.replace("\n", "").replace("\t", "").replace("　", "")
    text = re.sub(r"\s+", "", text)
    text = text.replace("“", '"').replace("”", '"')
    return text


def extract_balanced_json(text: str) -> Optional[str]:
    """
    从文本中提取第一个完整 JSON 对象子串（深度配对，字符串感知）。

    从首个 '{' 开始扫描，跟踪字符串与转义状态，遇到配平的 '}' 即返回；
    找不到完整对象返回 None。
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def safe_load_json(text: str) -> Optional[dict]:
    """
    宽松解析 LLM 输出：去代码块 → 压缩空白 → 中文引号 → 配对提取 → json.loads。

    返回 dict；任何一步失败返回 None（不抛异常）。
    注：不做单引号替换（会误伤字符串内单引号）；确有需要时由调用方二次尝试。
    """
    cleaned = normalize_json_text(strip_code_blocks(text))
    sub = extract_balanced_json(cleaned)
    if sub is None:
        return None
    try:
        data = json.loads(sub)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None
