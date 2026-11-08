# -*- coding: utf-8 -*-
"""列出网关可用模型 ID（OpenRouter / OpenCode Console / OpenCode Go 等）。

用法：
    python -m guide_eval.list_models --base-url https://openrouter.ai/api/v1 --key-env OPENROUTER_API_KEY
    python -m guide_eval.list_models --base-url https://opencode.ai/inference/go/openai/v1 --key-env OPENCODE_GO_API_KEY

用途：网关的模型 ID 会变（新增/下线/改名），填入 models.json 前先拉一遍真实列表。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .providers import load_env  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="列出 OpenAI 兼容网关的模型 ID")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--key-env", required=True, help="存放 API key 的环境变量名")
    ap.add_argument("--filter", default="", help="只显示包含该子串的 ID（不区分大小写）")
    args = ap.parse_args()

    load_env()
    import os

    key = os.getenv(args.key_env, "")
    if not key:
        raise SystemExit(f"环境变量 {args.key_env} 为空：请在 .env 中配置")
    try:
        from openai import OpenAI
    except Exception as e:
        raise SystemExit(f"需要 openai SDK：{e}")

    client = OpenAI(api_key=key, base_url=args.base_url, timeout=60)
    try:
        models = client.models.list()
    except Exception as e:
        raise SystemExit(f"拉取失败（{args.base_url}）：{e}")

    ids = sorted(m.id for m in models.data)
    if args.filter:
        ids = [i for i in ids if args.filter.lower() in i.lower()]
    print(f"# {args.base_url}  ({len(ids)} models)")
    for i in ids:
        print(i)


if __name__ == "__main__":
    main()
