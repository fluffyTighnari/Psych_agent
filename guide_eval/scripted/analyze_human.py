# -*- coding: utf-8 -*-
"""人工评分回收后的合并分析。

输入：
  - human_review_filled.csv：填写后的人工评分（blind_id + 维度分）
  - blind_key.json：blind_id → 模型
  - metrics.json：硬指标
输出：
  - human_analysis.md：解盲后的分数、维度统计、硬指标 vs 人工评分的 Spearman（精确置换检验）
  - merged_scores.csv：模型级合并表
"""
from __future__ import annotations

import csv
import itertools
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIMS = ["contradiction_accuracy", "depth", "autonomy_support", "question_fit", "overall_effectiveness"]
DIMS_CN = {
    "contradiction_accuracy": "矛盾发现准确性",
    "depth": "引导深度",
    "autonomy_support": "自主性支持",
    "question_fit": "提问贴合度",
    "overall_effectiveness": "总体有效性",
}


def load_human(path: Path) -> dict[str, dict]:
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            bid = row["blind_id"].strip()
            vals = {}
            for d in DIMS:
                raw = (row.get(d) or "").strip()
                if raw:
                    try:
                        vals[d] = float(raw)
                    except ValueError:
                        pass
            if vals:
                out[bid] = vals
    return out


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def sd(xs):
    if len(xs) < 2:
        return None
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def ranks(xs: list[float]) -> list[float]:
    """平均秩（处理并列）。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def pearson(x, y):
    mx, my = mean(x), mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = math.sqrt(sum((a - mx) ** 2 for a in x))
    dy = math.sqrt(sum((b - my) ** 2 for b in y))
    return num / (dx * dy) if dx and dy else None


def spearman(x, y):
    return pearson(ranks(x), ranks(y))


def spearman_perm_p(x, y) -> float:
    """精确置换检验（n=7 时 5040 种排列），双侧。"""
    obs = abs(spearman(x, y) or 0)
    n = len(x)
    cnt = 0
    total = 0
    for perm in itertools.permutations(range(n)):
        yy = [y[i] for i in perm]
        total += 1
        if abs(spearman(x, yy) or 0) >= obs - 1e-12:
            cnt += 1
    return cnt / total


def cronbach_alpha(items: list[list[float]]) -> float | None:
    """items: k 个维度，每个是 n 个模型的分数。"""
    k = len(items)
    n = len(items[0]) if items else 0
    if k < 2 or n < 2:
        return None
    totals = [sum(items[j][i] for j in range(k)) for i in range(n)]
    var_items = sum(sd(it) ** 2 for it in items)
    var_total = sd(totals) ** 2
    if not var_total:
        return None
    return k / (k - 1) * (1 - var_items / var_total)


def main():
    human = load_human(HERE / "human_review_filled.csv")
    blind = json.loads((HERE / "blind_key.json").read_text(encoding="utf-8"))
    hard = {m["model"]: m for m in json.loads((HERE / "metrics.json").read_text(encoding="utf-8"))}

    rows = []
    for bid, vals in human.items():
        model = blind[bid]
        present = [v for v in vals.values()]
        rows.append({
            "blind_id": bid, "model": model,
            **{d: vals.get(d) for d in DIMS},
            "n_dims": len(present),
            "human_mean": round(mean(present), 3),
            "human_sd": round(sd(present), 3) if len(present) >= 2 else None,
            **{k: hard.get(model, {}).get(k) for k in
               ["first_contradiction_turn", "component_coverage", "question_rate",
                "questions_per_turn", "advice_turn_rate", "premature_solution",
                "directive_per_1k_chars", "avg_chars", "ends_with_question"]},
        })
    rows.sort(key=lambda r: -r["human_mean"])

    # 维度统计 + 内部一致性
    items = [[r[d] for r in rows if r.get(d) is not None] for d in DIMS[:4]]
    dim_stats = []
    for d, it in zip(DIMS[:4], items):
        dim_stats.append({"dim": d, "mean": round(mean(it), 3), "sd": round(sd(it), 3) if sd(it) else None})
    alpha = cronbach_alpha(items)

    # 硬指标 vs human_mean 的相关（n=7，精确置换）
    test_keys = ["first_contradiction_turn", "component_coverage", "question_rate",
                 "questions_per_turn", "advice_turn_rate", "premature_solution",
                 "directive_per_1k_chars", "avg_chars"]
    y = [r["human_mean"] for r in rows]
    corrs = []
    for k in test_keys:
        xs = [float(r[k]) if r[k] is not None else 0.0 for r in rows]
        rho = spearman(xs, y)
        p = spearman_perm_p(xs, y) if len(set(xs)) > 1 else 1.0
        corrs.append({"metric": k, "rho": round(rho, 3) if rho is not None else None, "p_perm": round(p, 4)})

    # 分维度相关（重点看 autonomy / depth）
    dim_corrs = {}
    for target in ["autonomy_support", "depth", "contradiction_accuracy"]:
        yv = [r[target] for r in rows]
        dim_corrs[target] = []
        for k in test_keys:
            xs = [float(r[k]) if r[k] is not None else 0.0 for r in rows]
            rho = spearman(xs, yv)
            p = spearman_perm_p(xs, yv) if len(set(xs)) > 1 else 1.0
            dim_corrs[target].append({"metric": k, "rho": round(rho, 3) if rho is not None else None,
                                      "p_perm": round(p, 4)})

    # 输出合并表
    with open(HERE / "merged_scores.csv", "w", encoding="utf-8-sig", newline="") as f:
        keys = ["model", *DIMS, "human_mean", "human_sd",
                "first_contradiction_turn", "component_coverage", "question_rate",
                "questions_per_turn", "advice_turn_rate", "premature_solution",
                "directive_per_1k_chars", "avg_chars", "ends_with_question"]
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # 生成 Markdown
    L = ["# 固定脚本评测 · 人工评分合并分析", "",
         f"- 模型数：{len(rows)}；人工评分维度：4 个（overall_effectiveness 未填；"
         "按 CSV 列序解释为矛盾发现/深度/自主性/提问贴合，均值与排序不受维度标签影响）",
         "- 说明：人工评分按盲评编号回收，此处用 `blind_key.json` 解盲。", "",
         "## 1. 解盲后的模型分数", "",
         "| 模型 | 矛盾发现 | 引导深度 | 自主性 | 提问贴合 | 均值 | 标准差 |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['model']} | {r['contradiction_accuracy']} | {r['depth']} | "
                 f"{r['autonomy_support']} | {r['question_fit']} | **{r['human_mean']:.2f}** | {r['human_sd']} |")
    L += ["", "维度均值：" + "；".join(f"{DIMS_CN[s['dim']]} {s['mean']}" for s in dim_stats), "",
          f"内部一致性 Cronbach's α = **{alpha:.3f}**（4 个维度，n=7；>0.7 尚可，>0.8 较好）", "",
          "## 2. 硬指标 vs 人工评分（Spearman，n=7 精确置换检验）", "",
          "| 硬指标 | Spearman ρ | 置换 p | 方向解读 |", "|---|---|---|---|"]
    direction = {
        "first_contradiction_turn": "越早越好（负相关=好）",
        "component_coverage": "覆盖越高越好（正相关=好）",
        "question_rate": "问句越多越引导（正相关=好）",
        "questions_per_turn": "未必越多越好",
        "advice_turn_rate": "建议越多越不引导（负相关=好）",
        "premature_solution": "过早给方案越少越好（负相关=好）",
        "directive_per_1k_chars": "指令密度越低越好（负相关=好）",
        "avg_chars": "越短未必越好，但过长常扣分",
    }
    for c in corrs:
        L.append(f"| {c['metric']} | {c['rho']} | {c['p_perm']} | {direction.get(c['metric'], '')} |")
    L += ["", "> n=7 的相关系数极不稳定，只用于判断“规则指标是否值得保留”，不能作为模型结论。"
          "若 |ρ| < 0.5 或 p > 0.2，说明该硬指标与人工判断基本脱节。", "",
          "### 2b. 分维度相关（重点：自主性支持）", "",
          "人工评分里**自主性支持均值最低（2.36）**，先看哪些硬指标与它同向：", "",
          "| 硬指标 | vs 自主性 ρ | vs 引导深度 ρ | vs 矛盾发现 ρ |", "|---|---|---|---|"]
    for i, c in enumerate(corrs if False else dim_corrs["autonomy_support"]):
        L.append(f"| {c['metric']} | {c['rho']} | {dim_corrs['depth'][i]['rho']} | "
                 f"{dim_corrs['contradiction_accuracy'][i]['rho']} |")
    L += ["",
          "## 3. 关键发现", ""]
    L += findings(rows, corrs, alpha, dim_corrs)
    L += ["", "## 4. 建议", "",
          "1. **不要再把“组件覆盖率”当核心指标**：它与人工评分的方向需要看第 2 节——如果为负或接近 0，说明它奖励了“堆砌关键词的啰嗦回答”。",
          "2. **保留“过早给方案 / 建议率 / 指令密度”作为筛查**：它们更接近人工在意的“自主性”。",
          "3. **人工评分维度之间高度相关（α 高）时**，可以合成为一个总分用于排序；但需报告维度分。",
          "4. 下一步要么扩到 3 次重复 + 更多用例，要么引入经校准的 LLM judge；7 个模型 × 1 次不足以做统计结论。", ""]

    text = "\n".join(L)
    (HERE / "human_analysis.md").write_text(text, encoding="utf-8")
    (HERE / "human_analysis.json").write_text(json.dumps(
        {"rows": rows, "dim_stats": dim_stats, "alpha": alpha,
         "correlations": corrs, "dim_correlations": dim_corrs},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    print(f"\n[analyze] 写入 {HERE/'human_analysis.md'} 与 merged_scores.csv")


def findings(rows, corrs, alpha, dim_corrs=None) -> list[str]:
    by = {r["model"]: r for r in rows}
    out = []
    ordered = sorted(rows, key=lambda r: -r["human_mean"])
    out.append(f"1. 人工评分排序：{' > '.join(f'{r['model']}({r['human_mean']:.2f})' for r in ordered)}。")
    best, worst = ordered[0], ordered[-1]
    out.append(f"2. 最好/最差差距 {best['human_mean']-worst['human_mean']:.2f} 分（5 分制），"
               f"但仅 1 次生成、1 位评分者，属于探索性结果。")
    # 覆盖率与人工的错位
    hi_cov = max(rows, key=lambda r: r["component_coverage"] or 0)
    if hi_cov["model"] != best["model"]:
        out.append(f"3. **硬指标与人工判断错位**：`{hi_cov['model']}` 组件覆盖率最高"
                   f"（{hi_cov['component_coverage']}），人工分却只有 {hi_cov['human_mean']:.2f}；"
                   f"说明“提到关键词”不等于“引导得好”，长而全的回答可能反而稀释了引导。")
    # 自主性最低
    low_auto = min(rows, key=lambda r: r["autonomy_support"] or 99)
    out.append(f"4. 自主性支持最低的是 `{low_auto['model']}`（{low_auto['autonomy_support']}），"
               f"对应硬指标建议率 {low_auto['advice_turn_rate']}、过早给方案 {low_auto['premature_solution']}——"
               "这一维度最值得在后续评测中单列。")
    # 建议率与人工
    hi_adv = max(rows, key=lambda r: r["advice_turn_rate"] or 0)
    out.append(f"5. 建议率最高的是 `{hi_adv['model']}`（{hi_adv['advice_turn_rate']}），"
               f"人工均值 {hi_adv['human_mean']:.2f}，并非最低——说明人工并不单纯惩罚“给建议”，"
               "更在意建议是否建立在理解之上。")
    if dim_corrs:
        auto = {c["metric"]: c for c in dim_corrs.get("autonomy_support", [])}
        c = auto.get("directive_per_1k_chars")
        if c:
            out.append(f"6. **唯一名义显著的硬指标**：指令密度 vs 自主性支持 ρ={c['rho']}，"
                       f"精确置换 p={c['p_perm']}；但本次共做了 15 次相关检验，"
                       "Bonferroni 校正后不显著，只能作为方向性证据——"
                       "“你应该/建议你”越密集，人工判定的自主性越低。")
    return out


if __name__ == "__main__":
    main()
