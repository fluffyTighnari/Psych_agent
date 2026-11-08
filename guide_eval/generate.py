# -*- coding: utf-8 -*-
"""引导型咨询评测 · 多轮对话生成。

一条样本 = (case, condition, candidate_model)。生成时：
  用户模拟器（另一个人格，带隐藏背景/阻抗策略）↔ 被评测模型
结束后再用模拟器做一次「后测」（自评清晰度/洞察/自主性/行动意愿）。

注意：模拟器与候选模型应尽量不同源，否则会出现“同源模型互相配合”的偏差；
模拟器只负责扮演，不参与打分。
"""
from __future__ import annotations

import json
import time
from typing import Optional

from . import prompts
from .providers import ChatProvider, parse_json


# ------------------------------------------------------------------ 用例
def load_cases(path, limit: Optional[int] = None) -> list[dict]:
    data = json.loads(open(path, "r", encoding="utf-8").read())
    cases = data["cases"]
    return cases[:limit] if limit else cases


# ------------------------------------------------------------------ 渲染
def format_transcript(conv: list[dict]) -> str:
    """把 user/assistant 对话渲染成给判定器看的带轮次文本。"""
    lines = []
    turn = 0
    for m in conv:
        if m["role"] == "user":
            turn += 1
            lines.append(f"【用户第{turn}轮】{m['content']}")
        else:
            lines.append(f"【助手第{turn}轮】{m['content']}")
    return "\n".join(lines)


def _simulator_messages(case: dict, conv: list[dict]) -> list[dict]:
    """构造模拟器的 messages：视角反转（咨询师=user，自己=assistant）。"""
    sys = prompts.SIMULATOR_SYSTEM.format(background=case["background"])
    msgs = [{"role": "system", "content": sys}]
    for m in conv:
        role = "assistant" if m["role"] == "user" else "user"
        msgs.append({"role": role, "content": m["content"]})
    msgs.append({"role": "system", "content": "现在请给出你作为这位用户的下一句回复。只输出 JSON。"})
    return msgs


def _probe_messages(case: dict, conv: list[dict]) -> list[dict]:
    sys = (
        "你正在扮演一位刚结束心理对话的用户。全程保持用户身份，"
        "不要跳出角色，不要评价助手，不要使用咨询术语。\n\n"
        f"## 你的人物设定（供回忆）\n{case['background']}"
    )
    user = (
        f"下面是刚才的完整对话：\n\n{format_transcript(conv)}\n\n"
        f"{prompts.PROBE_PROMPT}"
    )
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


# ------------------------------------------------------------------ 单条生成
def run_conversation(case: dict, condition: str, candidate: ChatProvider,
                     simulator: ChatProvider, max_turns: int = 6) -> dict:
    conv: list[dict] = [{"role": "user", "content": case["opening"]}]
    guided_reasons: list[dict] = []
    turns: list[dict] = []
    ended = False
    error = ""

    for t in range(1, max_turns + 1):
        msgs = prompts.build_messages(condition, case, conv, guided_reasons)
        try:
            raw = candidate.chat(msgs, temperature=None)
        except Exception as e:
            error = f"candidate_error: {e}"
            break

        ended = raw.strip().startswith("【结束】")
        reply = raw.strip()
        if ended:
            reply = reply[len("【结束】"):].strip()
        conv.append({"role": "assistant", "content": reply})

        if condition == "guide_prod":
            guided_reasons.append({"role": "user", "content": conv[-2]["content"]})
            guided_reasons.append({"role": "guide", "content": reply})

        rec = {"turn": t, "user": conv[-2]["content"], "assistant": reply, "sim": {}}
        turns.append(rec)
        if ended:
            break

        # 用户模拟器回复下一句
        try:
            sim_raw = simulator.chat(_simulator_messages(case, conv), temperature=0.8)
            sim = parse_json(sim_raw)
        except Exception:
            sim = {"reply": "嗯，我继续说说……我也说不清楚。", "affect": -1, "disclosure": 0, "defensiveness": 1}
        nxt = str(sim.get("reply") or "").strip() or "……"
        rec["sim"] = {k: sim.get(k) for k in ("affect", "disclosure", "defensiveness")}
        conv.append({"role": "user", "content": nxt})

    # 后测（即使中途报错也尽量拿到）
    post: dict = {}
    post_error = ""
    try:
        post = parse_json(simulator.chat(_probe_messages(case, conv), temperature=0.5))
    except Exception as e:
        post_error = f"probe_error: {e}"

    return {
        "case_id": case["id"],
        "condition": condition,
        "turns": turns,
        "ended": ended,
        "error": error,
        "post": post,
        "post_error": post_error,
        "n_user_turns": sum(1 for m in conv if m["role"] == "user"),
        "conv": conv,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
