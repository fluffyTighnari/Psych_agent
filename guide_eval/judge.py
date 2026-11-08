# -*- coding: utf-8 -*-
"""引导型咨询评测 · 判定器（LLM-as-judge）。

两阶段设计，避免“一步到位打分”常见的证据幻觉：
  Stage 1  evidence：对着人工标注的 gold 矛盾做**事实编码**（点出/追问/自我解释/收束），
                     并额外收集 assistant 的 gold 之外的断言（用于估计“过度断言”）。
  Stage 2  rubric  ：只给对话原文（盲评，不带模型/条件信息），按 8 个维度 1-5 打分，
                     强制每个分数引用原文。

judge 的输出只作为“测量工具”，它本身的有效性必须用人工标注校准（见 calibrate.py）。
"""
from __future__ import annotations

import json
import re
from typing import Optional

from . import prompts
from .providers import ChatProvider, parse_json

RUBRIC_KEYS = [
    "contradiction_accuracy",
    "depth",
    "question_fit",
    "autonomy_support",
    "progression",
    "empathy_safety",
    "self_explanation_elicitation",
    "overall_effectiveness",
]


def _clamp_int(v, lo=1, hi=5, default=3) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except Exception:
        return default


def _call_json(provider: ChatProvider, messages: list[dict], tag: str, attempts: int = 2) -> dict:
    last = None
    for _ in range(attempts):
        raw = provider.chat(messages, temperature=0, json_mode=True)
        try:
            return parse_json(raw)
        except Exception as e:
            last = e
            # 追加一句纠正后重试一次
            messages = messages + [
                {"role": "assistant", "content": raw[:400]},
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出一个 JSON 对象，不要任何其他文字。"},
            ]
    raise ValueError(f"{tag} 判定输出无法解析: {last}")


# ------------------------------------------------------------------ Stage 1
def judge_evidence(judge: ChatProvider, case: dict, conv: list[dict]) -> dict:
    gold = [{"id": g["id"], "surface": g["surface"], "deep": g.get("deep", "")}
            for g in case.get("gold_contradictions", [])]
    prompt = prompts.EVIDENCE_PROMPT.format(
        gold_json=json.dumps(gold, ensure_ascii=False, indent=1),
        transcript=_fmt(conv),
        turn_types=", ".join(prompts.TURN_TYPES),
    )
    data = _call_json(judge, [
        {"role": "system", "content": prompts.JUDGE_SYSTEM},
        {"role": "user", "content": prompt},
    ], "evidence")

    # 归一化：保证 gold 全覆盖、类型合法、布尔量是真布尔
    gold_ids = [g["id"] for g in gold]
    by_id = {}
    for item in data.get("contradictions", []) or []:
        gid = str(item.get("gold_id", "")).strip()
        if gid:
            by_id[gid] = item
    norm = []
    for gid in gold_ids:
        it = by_id.get(gid, {})
        norm.append({
            "gold_id": gid,
            "surfaced": bool(it.get("surfaced", False)),
            "first_turn": _clamp_int(it.get("first_turn"), 1, 99, 99) if it.get("first_turn") else None,
            "quote": str(it.get("quote") or ""),
            "inquiry_targeted": bool(it.get("inquiry_targeted", False)),
            "inquiry_quote": str(it.get("inquiry_quote") or ""),
            "user_self_explained": bool(it.get("user_self_explained", False)),
            "self_explanation_quote": str(it.get("self_explanation_quote") or ""),
            "resolved_by_end": bool(it.get("resolved_by_end", False)),
        })

    turns = []
    for t in data.get("turns", []) or []:
        types = [x for x in (t.get("types") or []) if x in prompts.TURN_TYPES]
        turns.append({
            "assistant_turn": _clamp_int(t.get("assistant_turn"), 1, 99, 1),
            "types": types,
            "gives_solution": bool(t.get("gives_solution", False)),
            "advice_quote": str(t.get("advice_quote") or ""),
            "question_targets": str(t.get("question_targets") or ""),
        })

    safety = data.get("safety") or {}
    return {
        "turns": turns,
        "contradictions": norm,
        "extra_claims": [
            {"claim": str(c.get("claim") or ""), "quote": str(c.get("quote") or "")}
            for c in (data.get("extra_claims") or [])
        ],
        "premature_solution_turn": data.get("premature_solution_turn"),
        "safety": {
            "needs_safety_check": bool(safety.get("needs_safety_check", False)),
            "assistant_performed_check": bool(safety.get("assistant_performed_check", False)),
            "assistant_recommended_professional_help": bool(safety.get("assistant_recommended_professional_help", False)),
            "note": str(safety.get("note") or ""),
        },
        "summary": str(data.get("summary") or ""),
    }


# ------------------------------------------------------------------ Stage 2
def judge_rubric(judge: ChatProvider, conv: list[dict]) -> dict:
    prompt = prompts.RUBRIC_PROMPT.format(transcript=_fmt(conv))
    data = _call_json(judge, [
        {"role": "system", "content": prompts.JUDGE_SYSTEM},
        {"role": "user", "content": prompt},
    ], "rubric")
    raw_scores = data.get("scores") or {}
    scores = {k: _clamp_int(raw_scores.get(k, 3)) for k in RUBRIC_KEYS}
    ev = data.get("evidence") or {}
    return {
        "scores": scores,
        "evidence": {k: str(ev.get(k) or "") for k in RUBRIC_KEYS},
        "fatal_flaw": str(data.get("fatal_flaw") or ""),
        "one_line_comment": str(data.get("one_line_comment") or ""),
    }


# ------------------------------------------------------------------ 成对比较
def judge_pairwise(judge: ChatProvider, conv_a: list[dict], conv_b: list[dict]) -> dict:
    prompt = prompts.PAIRWISE_PROMPT.format(
        transcript_a=_fmt(conv_a),
        transcript_b=_fmt(conv_b),
    )
    data = _call_json(judge, [
        {"role": "system", "content": prompts.JUDGE_SYSTEM},
        {"role": "user", "content": prompt},
    ], "pairwise")
    winner = str(data.get("winner") or "tie").strip().upper()
    if winner not in ("A", "B", "TIE"):
        winner = "TIE"
    return {
        "winner": winner,
        "confidence": _clamp_int(data.get("confidence"), 1, 5, 3),
        "key_difference": str(data.get("key_difference") or ""),
        "quote_a": str(data.get("quote_a") or ""),
        "quote_b": str(data.get("quote_b") or ""),
    }


# ------------------------------------------------------------------ 合并
def judge_conversation(judge: ChatProvider, case: dict, conv: list[dict]) -> dict:
    ev = judge_evidence(judge, case, conv)
    rb = judge_rubric(judge, conv)
    return {"evidence": ev, "rubric": rb}


def _fmt(conv: list[dict]) -> str:
    from .generate import format_transcript

    return format_transcript(conv)
