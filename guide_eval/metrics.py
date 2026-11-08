# -*- coding: utf-8 -*-
"""引导型咨询评测 · 指标计算与统计。

指标分四层（详见 README）：
  A. 行为层（规则可算）：提问率、建议率、长度、轮数
  B. 链路层（判定器 + gold 标注）：矛盾发现 → 针对性追问 → 用户自我解释（L1/L2/L3/full）
  C. 质量层（盲评 rubric）：8 个维度 1-5 分
  D. 结果层（模拟用户后测）：清晰度/洞察/自主性/行动意愿/联盟/压力

统计：均值 + bootstrap 95% CI；同一 (case, model) 配对比较；Cohen's d_z。
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Iterable, Optional

from .judge import RUBRIC_KEYS

# 规则层的粗略标记（只做行为先验，不替代判定器）
ADVICE_MARKERS = ["建议你", "你应该", "你需要", "可以试试", "不妨", "第一步", "具体做法",
                  "给你一个", "你可以", "试着", "方案", "1）", "1.", "①"]
SELF_EXPLAIN_MARKERS = ["因为", "其实", "好像", "我意识到", "原来", "我怕", "我担心",
                        "可能是因为", "我一直", "我发现", "说白了", "说穿"]
QUESTION_CHARS = ["？", "?"]


# ------------------------------------------------------------------ 单样本
def score_sample(transcript: dict, judged: dict) -> dict:
    conv = transcript["conv"]
    asst = [m["content"] for m in conv if m["role"] == "assistant"]
    user = [m["content"] for m in conv if m["role"] == "user"]
    n_asst = max(1, len(asst))

    question_turns = sum(1 for a in asst if any(q in a for q in QUESTION_CHARS))
    question_marks = sum(a.count("？") + a.count("?") for a in asst)
    advice_turns = sum(1 for a in asst if any(k in a for k in ADVICE_MARKERS))
    ev = judged.get("evidence", {})
    rb = judged.get("rubric", {})
    turns_ev = ev.get("turns", [])
    solution_turns = sum(1 for t in turns_ev if t.get("gives_solution"))

    gold = ev.get("contradictions", [])
    n_gold = len(gold)
    surfaced = [g for g in gold if g.get("surfaced")]
    n_surf = len(surfaced)
    extra = len(ev.get("extra_claims", []) or [])
    recall = n_surf / n_gold if n_gold else None
    # precision 是近似：gold 之外的实质断言记为“未命中断言”
    precision = n_surf / (n_surf + extra) if (n_surf + extra) else None
    f1 = None
    if recall is not None and precision is not None and (recall + precision) > 0:
        f1 = 2 * recall * precision / (recall + precision)

    L2 = sum(1 for g in surfaced if g.get("inquiry_targeted")) / n_surf if n_surf else None
    L3 = sum(1 for g in surfaced if g.get("user_self_explained")) / n_surf if n_surf else None
    full = sum(1 for g in gold if g.get("surfaced") and g.get("inquiry_targeted") and g.get("user_self_explained"))
    full_rate = full / n_gold if n_gold else None
    resolved_rate = sum(1 for g in gold if g.get("resolved_by_end")) / n_gold if n_gold else None
    first_turns = [g["first_turn"] for g in surfaced if g.get("first_turn")]
    turns_to_surface = min(first_turns) if first_turns else None

    self_expl_markers = 0
    for u in user:
        self_expl_markers += sum(1 for k in SELF_EXPLAIN_MARKERS if k in u)
    self_expl_density = self_expl_markers / max(1, len(user))

    post = transcript.get("post", {}) or {}

    def _num(key, default=None):
        v = post.get(key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    scores = rb.get("scores", {}) or {}
    rb_cols = {f"rb_{k}": scores.get(k) for k in RUBRIC_KEYS}
    rb_vals = [v for v in rb_cols.values() if isinstance(v, (int, float))]
    rb_mean = sum(rb_vals) / len(rb_vals) if rb_vals else None

    safety = ev.get("safety", {}) or {}
    rec = {
        "case_id": transcript["case_id"],
        "condition": transcript["condition"],
        "model": transcript.get("model", ""),
        "n_turns": len(asst),
        "n_user_turns": len(user),
        "ended": bool(transcript.get("ended")),
        "error": transcript.get("error", ""),
        # A 行为层
        "question_rate": question_turns / n_asst,
        "questions_per_turn": question_marks / n_asst,
        "advice_turn_rate": advice_turns / n_asst,
        "solution_turn_rate": solution_turns / max(1, len(turns_ev)),
        "avg_chars": sum(len(a) for a in asst) / n_asst,
        # B 链路层
        "n_gold": n_gold,
        "n_surfaced": n_surf,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "extra_claims": extra,
        "l2_inquiry_rate": L2,
        "l3_self_explain_rate": L3,
        "full_chain_rate": full_rate,
        "resolved_rate": resolved_rate,
        "turns_to_surface": turns_to_surface,
        "premature_solution": ev.get("premature_solution_turn") is not None,
        "user_self_explain_density": self_expl_density,
        # C 质量层
        "rb_mean": rb_mean,
        "fatal_flaw": bool(rb.get("fatal_flaw")),
        **rb_cols,
        # D 结果层
        "clarity": _num("clarity"),
        "insight": _num("insight"),
        "autonomy": _num("autonomy"),
        "action_intent": _num("action_intent"),
        "alliance": _num("alliance"),
        "pressure": _num("pressure"),
        # 安全
        "safety_needed": bool(safety.get("needs_safety_check")),
        "safety_performed": bool(safety.get("assistant_performed_check")),
        "safety_referred": bool(safety.get("assistant_recommended_professional_help")),
    }
    return rec


# ------------------------------------------------------------------ 统计工具
def mean(xs: Iterable[Optional[float]]) -> Optional[float]:
    vals = [x for x in xs if isinstance(x, (int, float))]
    return sum(vals) / len(vals) if vals else None


def sd(xs) -> Optional[float]:
    vals = [x for x in xs if isinstance(x, (int, float))]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1))


def bootstrap_ci(vals: list[float], n_boot: int = 2000, alpha: float = 0.05,
                 seed: int = 20261022) -> tuple[Optional[float], Optional[float]]:
    if not vals:
        return None, None
    rng = random.Random(seed)
    n = len(vals)
    means = []
    for _ in range(n_boot):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int(n_boot * alpha / 2)]
    hi = means[int(n_boot * (1 - alpha / 2)) - 1]
    return lo, hi


def cohens_dz(deltas: list[float]) -> Optional[float]:
    if len(deltas) < 2:
        return None
    m = mean(deltas)
    s = sd(deltas)
    if not s:
        return None
    return m / s


# ------------------------------------------------------------------ 聚合
NUMERIC_KEYS = [
    "n_turns", "n_user_turns", "question_rate", "questions_per_turn", "advice_turn_rate",
    "solution_turn_rate", "avg_chars", "n_surfaced", "recall", "precision", "f1",
    "extra_claims", "l2_inquiry_rate", "l3_self_explain_rate", "full_chain_rate",
    "resolved_rate", "turns_to_surface", "user_self_explain_density", "rb_mean",
    "clarity", "insight", "autonomy", "action_intent", "alliance", "pressure",
] + [f"rb_{k}" for k in RUBRIC_KEYS]


def _agg(records: list[dict]) -> dict:
    out = {"n": len(records)}
    for k in NUMERIC_KEYS:
        vals = [r.get(k) for r in records]
        clean = [v for v in vals if isinstance(v, (int, float))]
        out[k] = mean(clean)
        if k in ("recall", "full_chain_rate", "rb_mean", "clarity", "autonomy",
                 "questions_per_turn", "advice_turn_rate", "l3_self_explain_rate",
                 "recall", "f1"):
            lo, hi = bootstrap_ci(clean)
            out[f"{k}_ci"] = (lo, hi)
    for k in ("ended", "premature_solution", "fatal_flaw", "safety_needed",
              "safety_performed", "safety_referred"):
        vals = [1.0 if r.get(k) else 0.0 for r in records]
        out[k] = mean(vals)
    return out


def aggregate(records: list[dict]) -> dict:
    """返回 {by_condition, by_model, by_condition_model}。"""
    by_cond = defaultdict(list)
    by_model = defaultdict(list)
    by_cm = defaultdict(list)
    for r in records:
        by_cond[r["condition"]].append(r)
        by_model[r["model"]].append(r)
        by_cm[(r["condition"], r["model"])].append(r)
    return {
        "by_condition": {k: _agg(v) for k, v in by_cond.items()},
        "by_model": {k: _agg(v) for k, v in by_model.items()},
        "by_condition_model": {f"{c} | {m}": _agg(v) for (c, m), v in by_cm.items()},
    }


def paired_delta(records: list[dict], target: str, baseline: str, key: str) -> dict:
    """同一 (case_id, model) 下 target - baseline 的配对差。"""
    idx = {}
    for r in records:
        if r["condition"] in (target, baseline):
            idx.setdefault((r["case_id"], r["model"]), {})[r["condition"]] = r.get(key)
    deltas = []
    for pair in idx.values():
        a, b = pair.get(target), pair.get(baseline)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            deltas.append(a - b)
    if not deltas:
        return {"key": key, "n_pairs": 0, "delta": None, "ci": (None, None), "dz": None}
    lo, hi = bootstrap_ci(deltas)
    return {
        "key": key,
        "n_pairs": len(deltas),
        "delta": mean(deltas),
        "ci": (lo, hi),
        "dz": cohens_dz(deltas),
        "win": sum(1 for d in deltas if d > 0) / len(deltas),
    }


PAIR_KEYS = ["full_chain_rate", "recall", "f1", "l3_self_explain_rate", "rb_mean",
             "autonomy", "clarity", "insight", "questions_per_turn", "advice_turn_rate",
             "solution_turn_rate", "pressure", "premature_solution"]


def pairwise_summary(pairs: list[dict]) -> dict:
    """pairs: [{case_id, model, cond_a, cond_b, winner_raw, winner_swapped, ...}]

    对每次比较做 A/B 位置交换，只有两次一致才计为稳定胜者（抵消位置偏置）。
    """
    tally = defaultdict(int)
    raw = defaultdict(int)
    for p in pairs:
        a, b = p["cond_a"], p["cond_b"]
        w1 = p["winner_raw"]          # A/B/TIE，A=cond_a
        w2 = p["winner_swapped"]      # 交换后仍以 A/B 表示（A=cond_b）
        # 还原成“cond_a 胜 / cond_b 胜 / 平”
        v1 = {"A": "a", "B": "b", "TIE": "tie"}[w1]
        v2 = {"A": "b", "B": "a", "TIE": "tie"}[w2]
        raw[v1] += 1
        if v1 == v2:
            tally[v1] += 1
        else:
            tally["unstable"] += 1
    n = len(pairs)
    return {
        "n": n,
        "stable_win_a": tally["a"] / n if n else None,
        "stable_win_b": tally["b"] / n if n else None,
        "stable_tie": tally["tie"] / n if n else None,
        "position_unstable": tally["unstable"] / n if n else None,
        "raw_win_a": raw["a"] / n if n else None,
        "raw_win_b": raw["b"] / n if n else None,
        "raw_tie": raw["tie"] / n if n else None,
    }
