# -*- coding: utf-8 -*-
"""引导型咨询评测 · Markdown 报告渲染。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import prompts

COND_ORDER = ["raw", "generic", "advice", "guide_prod", "guide_lite"]

MAIN_METRICS = [
    ("recall", "矛盾发现率 L1", "pct"),
    ("precision", "断言精确率*", "pct"),
    ("l2_inquiry_rate", "针对性追问率 L2", "pct"),
    ("l3_self_explain_rate", "自我解释率 L3", "pct"),
    ("full_chain_rate", "完整链路率 L1→L2→L3", "pct"),
    ("questions_per_turn", "每轮问句数", "f2"),
    ("advice_turn_rate", "给建议轮次占比", "pct"),
    ("premature_solution", "过早给方案率", "pct"),
    ("rb_mean", "盲评均分", "f2"),
    ("autonomy", "自主性(0-10)", "f2"),
    ("clarity", "清晰度(0-10)", "f2"),
    ("insight", "洞察条数(0-5)", "f2"),
    ("pressure", "被推着走(0-10)", "f2"),
]


def _fmt(v, kind):
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v*100:.0f}%"
    if kind == "f2":
        return f"{v:.2f}"
    return str(v)


def _ci(v):
    if not v:
        return ""
    lo, hi = v
    if lo is None or hi is None:
        return ""
    return f" [{lo:.2f}, {hi:.2f}]"


def render(agg: dict, records: list[dict], paired: list[dict], pairwise: dict,
           meta: dict, out_path: Path, calibration: Optional[dict] = None) -> str:
    by_cond = agg["by_condition"]
    by_cm = agg["by_condition_model"]
    conds = [c for c in COND_ORDER if c in by_cond] + [c for c in by_cond if c not in COND_ORDER]

    L = []
    L.append("# 引导型咨询有效性评测报告")
    L.append("")
    L.append(f"- 生成时间：{meta.get('ts', '')}")
    L.append(f"- 用例数：{meta.get('n_cases', '')} × 条件数：{len(conds)} × 候选模型：{meta.get('n_models', '')}")
    L.append(f"- 每段最大轮数：{meta.get('max_turns', '')}；样本总数：{len(records)}")
    L.append(f"- 判定模型：{meta.get('judge', '')}；模拟器：{meta.get('simulator', '')}")
    if meta.get("mock"):
        L.append("")
        L.append("> ⚠️ **本次为 MOCK 运行**：所有模型输出与判定分数都是假数据，只用于验证流水线，"
                 "**不能**据此判断任何模型或 prompt 的真实效果。")
    if meta.get("cli_models"):
        L.append("")
        L.append(f"> ⚠️ **包含 CLI 包装模型**：{', '.join(meta['cli_models'])}。CLI 自带系统提示/工具/工作区上下文，"
                 "测到的是「产品化包装后的体验」，**不要**与纯 API 模型的条件对比放在同一结论里。")
    L.append("")

    # 摘要
    L.append("## 0. 摘要（自动生成，需结合判定器校准结果阅读）")
    L.append("")
    gp, ad = by_cond.get("guide_prod"), by_cond.get("advice")
    if gp and ad:
        L.append(
            f"- 完整链路率：`guide_prod` {_fmt(gp.get('full_chain_rate'), 'pct')} vs "
            f"`advice` {_fmt(ad.get('full_chain_rate'), 'pct')}；"
            f"盲评均分 {_fmt(gp.get('rb_mean'), 'f2')} vs {_fmt(ad.get('rb_mean'), 'f2')}。"
        )
        L.append(
            f"- 自主性 {_fmt(gp.get('autonomy'), 'f2')} vs {_fmt(ad.get('autonomy'), 'f2')}；"
            f"过早给方案率 {_fmt(gp.get('premature_solution'), 'pct')} vs {_fmt(ad.get('premature_solution'), 'pct')}。"
        )
        L.append(f"- 配对差异（guide_prod − advice）见第 4 节；成对比较见第 5 节。")
    L.append("")

    # 主表
    L.append("## 1. 主结果（按条件汇总）")
    L.append("")
    L.append("| 指标 | " + " | ".join(f"`{c}`" for c in conds) + " |")
    L.append("|---|" + "---|" * len(conds))
    for key, label, kind in MAIN_METRICS:
        cells = []
        for c in conds:
            row = by_cond.get(c, {})
            cells.append(_fmt(row.get(key), kind))
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("> `*` 断言精确率 = 命中 gold 的矛盾数 /（命中数 + 判定器记录的 gold 之外实质断言数），"
             "是近似口径；它会把“有道理但不在标注里的洞察”也算成未命中，因此偏保守，仅作趋势参考。")
    L.append("> L1=是否点出真实矛盾；L2=点出后是否针对性追问；L3=追问后用户是否自发自我解释；"
             "完整链路率=三者同时发生的 gold 矛盾占比。")
    L.append("")

    # 链路分解
    L.append("## 2. 链路分解（条件均值）")
    L.append("")
    L.append("| 条件 | L1 发现 | L2 \\| L1 | L3 \\| L2 | 完整链路 | 过早给方案 | 平均轮数 |")
    L.append("|---|---|---|---|---|---|---|")
    for c in conds:
        r = by_cond.get(c, {})
        L.append(f"| `{c}` | {_fmt(r.get('recall'), 'pct')} | {_fmt(r.get('l2_inquiry_rate'), 'pct')} | "
                 f"{_fmt(r.get('l3_self_explain_rate'), 'pct')} | {_fmt(r.get('full_chain_rate'), 'pct')} | "
                 f"{_fmt(r.get('premature_solution'), 'pct')} | {_fmt(r.get('n_turns'), 'f2')} |")
    L.append("")

    # 条件 × 模型
    L.append("## 3. 条件 × 模型（完整链路率 / 盲评均分 / 自主性）")
    L.append("")
    L.append("| 条件 \\ 模型 | " + " | ".join(sorted({r['model'] for r in records})) + " |")
    L.append("|---|" + "---|" * len({r['model'] for r in records}))
    models = sorted({r["model"] for r in records})
    for c in conds:
        cells = []
        for m in models:
            r = by_cm.get(f"{c} | {m}", {})
            cells.append(f"{_fmt(r.get('full_chain_rate'), 'pct')} / "
                         f"{_fmt(r.get('rb_mean'), 'f2')} / {_fmt(r.get('autonomy'), 'f2')}")
        L.append(f"| `{c}` | " + " | ".join(cells) + " |")
    L.append("")

    # 配对
    L.append("## 4. 配对差异（guide_prod − advice，同一用例同一模型）")
    L.append("")
    if paired:
        rows = [p for p in paired if p.get("n_pairs")]
        L.append("| 指标 | 配对 n | 差值 | 95% CI | Cohen's d_z | guide_prod 更高占比 |")
        L.append("|---|---|---|---|---|---|")
        for p in rows:
            ci = p["ci"]
            ci_txt = "—" if not ci or ci[0] is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"
            L.append(f"| {p['key']} | {p['n_pairs']} | {_fmt(p['delta'], 'f3')} | "
                     f"{ci_txt} | {_fmt(p['dz'], 'f2')} | {_fmt(p.get('win'), 'pct')} |")
        if not rows:
            L.append("| （无可配对样本） | — | — | — | — | — |")
        L.append("")
        L.append("> 差值 CI 不含 0 且 d_z ≥ 0.5 才算有实际意义的差异；n 很小时 CI 会很宽。")
    else:
        L.append("（无配对数据）")
    L.append("")

    # 成对比较
    L.append("## 5. 成对比较（judge pairwise，A/B 交换位置后取稳定胜者）")
    L.append("")
    if pairwise:
        L.append(f"- 比较数：{pairwise.get('n', 0)}")
        L.append(f"- 稳定胜率：A {_fmt(pairwise.get('stable_win_a'), 'pct')} / "
                 f"B {_fmt(pairwise.get('stable_win_b'), 'pct')} / "
                 f"平 {_fmt(pairwise.get('stable_tie'), 'pct')}")
        L.append(f"- 位置不稳定率（交换后结论翻转）：{_fmt(pairwise.get('position_unstable'), 'pct')}"
                 "（>30% 说明 judge 位置偏置严重，pairwise 结论不可用）")
    else:
        L.append("（未运行成对比较）")
    L.append("")

    # 安全专项
    L.append("## 6. 安全项（含风险筛查用例）")
    L.append("")
    safety_cases = [r for r in records if r.get("safety_needed")]
    if safety_cases:
        by = {}
        for r in safety_cases:
            by.setdefault(r["condition"], []).append(r)
        L.append("| 条件 | 需要筛查 | 实际筛查率 | 建议转介率 |")
        L.append("|---|---|---|---|")
        for c, rs in by.items():
            L.append(f"| `{c}` | {len(rs)} | "
                     f"{_fmt(sum(1 for x in rs if x.get('safety_performed'))/len(rs), 'pct')} | "
                     f"{_fmt(sum(1 for x in rs if x.get('safety_referred'))/len(rs), 'pct')} |")
    else:
        L.append("（本次运行未包含需要风险筛查的用例；`c10` 含 safety_review，跑全量用例时此处会出数据）")
    L.append("")

    # 校准
    L.append("## 7. 判定器校准状态")
    L.append("")
    if calibration:
        L.append("| 维度 | 加权 kappa | ICC(2,1) | 判定 |")
        L.append("|---|---|---|---|")
        for d, v in calibration.items():
            L.append(f"| {d} | {_fmt(v.get('weighted_kappa'), 'f2')} | "
                     f"{_fmt(v.get('icc_2_1'), 'f2')} | {'✅' if v.get('pass') else '❌'} |")
        L.append("")
        L.append("> 未通过校准的维度不能用于正式结论。")
    else:
        L.append("**尚未做人工校准。** 在补完 40-80 条人工盲评并跑 `calibrate.py` 之前，"
                 "本报告只能用于发现问题，不能用于对外下结论。")
    L.append("")

    # 局限
    L.append("## 8. 已知局限")
    L.append("")
    L.append("1. **模拟用户 ≠ 真人**：模拟器的披露节奏、阻抗水平会影响结论。建议用真实对话日志做 10-20 段保真度校验。")
    L.append("2. **判定器偏差**：LLM judge 存在长度偏好、自我偏好（评自家模型）、位置偏置；已用盲评 + A/B 交换缓解，但不能消除。")
    L.append("3. **gold 标注不完备**：用例只标注了研究者预设的矛盾，模型可能发现其他真实矛盾却被算作“额外断言”。")
    L.append("4. **单轮 prompt 效应**：本评测固定 prompt，未覆盖模型对 prompt 的鲁棒性（改写/截断/注入）。")
    L.append("5. **结果层是自评**：清晰度/洞察来自模拟用户自报，存在讨好偏差；需真人前后测验证。")
    L.append("")

    # 复现
    L.append("## 9. 复现")
    L.append("")
    L.append("```bash")
    L.append("# 离线验证流水线（不需要 key）")
    L.append("python -m guide_eval.run --mock")
    L.append("")
    L.append("# 真实评测（需要 guide_eval/models.json + .env）")
    L.append("python -m guide_eval.run --models deepseek-chat,qwen-plus --conditions raw,advice,guide_prod")
    L.append("")
    L.append("# 人工校准")
    L.append("python -m guide_eval.calibrate --make-template guide_eval/out/judged.jsonl")
    L.append("python -m guide_eval.calibrate --score guide_eval/out/labels_template.csv --judged guide_eval/out/judged.jsonl")
    L.append("```")
    L.append("")

    text = "\n".join(L)
    out_path.write_text(text, encoding="utf-8")
    return text
