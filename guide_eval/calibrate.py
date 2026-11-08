# -*- coding: utf-8 -*-
"""引导型咨询评测 · 判定器校准（judge 自身有效性验证）。

流程：
1) 从 judged 结果里抽一批样本（默认全部），生成**盲评**模板：
   - labels_template.csv：只含 sample_id + 空的 4 个人工评分列，不含模型/条件
   - labels_key.json：sample_id → (model, condition) 的私密映射，评分时别看
2) 人工按 rubric 打分（1-5）。
3) 运行 --score：对齐人工分与 judge 分，输出
   - 每个维度的 Pearson r、二次加权 kappa、ICC(2,1)、平均绝对差
   - 一致性门槛（默认：加权 kappa ≥ 0.40 且 ICC ≥ 0.50 才算该维度可用）
   - 分歧最大的样本清单（用于回看 rubric 措辞）

判定器不过关时，不要拿它的分数下结论；应先改 rubric/换 judge/加 few-shot 示例。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path
from typing import Optional

CALIB_DIMS = ["contradiction_accuracy", "autonomy_support",
              "self_explanation_elicitation", "overall_effectiveness"]
DIM_NAMES_CN = {
    "contradiction_accuracy": "矛盾识别准确性",
    "autonomy_support": "自主性支持",
    "self_explanation_elicitation": "自我解释诱发",
    "overall_effectiveness": "总体引导有效性",
}
N_BINS = 5  # 1..5


# ------------------------------------------------------------------ 生成本
def make_template(judged_path: str, out_dir: str, sample_ratio: float = 1.0,
                  seed: int = 7) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(l) for l in open(judged_path, encoding="utf-8") if l.strip()]
    rng = random.Random(seed)
    if sample_ratio < 1.0:
        rows = rng.sample(rows, max(1, int(len(rows) * sample_ratio)))
    rng.shuffle(rows)  # 打乱顺序，避免评分者推断条件

    label_rows = []
    key = {}
    for i, r in enumerate(rows, 1):
        sid = f"S{i:03d}"
        key[sid] = {"model": r.get("model", ""), "condition": r.get("condition", ""),
                    "case_id": r.get("case_id", "")}
        label_rows.append({
            "sample_id": sid,
            "transcript": r.get("transcript", ""),
            **{d: "" for d in CALIB_DIMS},
            "notes": "",
        })

    with open(out / "labels_template.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sample_id", "transcript", *CALIB_DIMS, "notes"])
        w.writeheader()
        w.writerows(label_rows)
    (out / "labels_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[calibrate] 模板已写入 {out/'labels_template.csv'}（{len(label_rows)} 条，盲评）")
    print(f"[calibrate] 私密映射：{out/'labels_key.json'}（评分时不要打开）")
    print("[calibrate] 提示：可在 Excel/Numbers 里评分，1=最差 5=最好；不确定就留空。")


# ------------------------------------------------------------------ 一致性
def quadratic_weighted_kappa(y1: list[int], y2: list[int], k: int = N_BINS) -> Optional[float]:
    pairs = [(a, b) for a, b in zip(y1, y2) if a and b]
    if not pairs:
        return None
    n = len(pairs)
    obs = [[0] * k for _ in range(k)]
    for a, b in pairs:
        obs[a - 1][b - 1] += 1
    r1 = [sum(obs[i]) for i in range(k)]
    r2 = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    po = pe = 0.0
    for i in range(k):
        for j in range(k):
            w = 1 - ((i - j) ** 2) / ((k - 1) ** 2)
            po += w * obs[i][j] / n
            pe += w * (r1[i] / n) * (r2[j] / n)
    if pe >= 1:
        return None
    return (po - pe) / (1 - pe)


def pearson(x: list[float], y: list[float]) -> Optional[float]:
    if len(x) < 2:
        return None
    mx, my = sum(x) / len(x), sum(y) / len(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = math.sqrt(sum((a - mx) ** 2 for a in x))
    dy = math.sqrt(sum((b - my) ** 2 for b in y))
    return num / (dx * dy) if dx and dy else None


def icc_2_1(x: list[float], y: list[float]) -> Optional[float]:
    """two-way random effects, single rater, absolute agreement。"""
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    n = len(pairs)
    if n < 3:
        return None
    k = 2
    grand = sum(a + b for a, b in pairs) / (n * k)
    # 行（被试）均值
    row_means = [(a + b) / k for a, b in pairs]
    col_means = [sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n]
    ss_rows = k * sum((m - grand) ** 2 for m in row_means)
    ss_cols = n * sum((m - grand) ** 2 for m in col_means)
    ss_total = sum((v - grand) ** 2 for a, b in pairs for v in (a, b))
    ss_err = ss_total - ss_rows - ss_cols
    df_rows, df_cols, df_err = n - 1, k - 1, (n - 1) * (k - 1)
    if df_err <= 0:
        return None
    msr = ss_rows / df_rows
    msc = ss_cols / df_cols
    mse = ss_err / df_err
    denom = msr + (k - 1) * mse + k * (msc - mse) / n
    return (msr - mse) / denom if denom else None


# ------------------------------------------------------------------ 评分
def score(labels_csv: str, judged_path: str, out_dir: str,
          kappa_gate: float = 0.40, icc_gate: float = 0.50) -> dict:
    judged = {f"{r['model']}__{r['condition']}__{r['case_id']}": r
              for r in (json.loads(l) for l in open(judged_path, encoding="utf-8") if l.strip())}
    key = json.loads((Path(out_dir) / "labels_key.json").read_text(encoding="utf-8"))

    human: dict[str, dict] = {}
    with open(labels_csv, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sid = row["sample_id"].strip()
            if sid not in key:
                continue
            vals = {}
            for d in CALIB_DIMS:
                raw = (row.get(d) or "").strip()
                if raw:
                    try:
                        vals[d] = int(float(raw))
                    except ValueError:
                        pass
            human[sid] = vals

    # 对齐：judged 的键是 model__condition__case_id
    result = {}
    for d in CALIB_DIMS:
        hs, js, sids = [], [], []
        for sid, meta in key.items():
            key3 = f"{meta['model']}__{meta['condition']}__{meta['case_id']}"
            jr = judged.get(key3)
            if not jr or d not in human.get(sid, {}):
                continue
            jd = jr.get("rubric", {}).get("scores", {}).get(d)
            if jd is None:
                continue
            hs.append(human[sid][d])
            js.append(int(jd))
            sids.append(sid)
        n = len(hs)
        r = pearson([float(v) for v in hs], [float(v) for v in js]) if n >= 2 else None
        kappa = quadratic_weighted_kappa(hs, js) if n >= 2 else None
        icc = icc_2_1(hs, js) if n >= 2 else None
        mad = sum(abs(a - b) for a, b in zip(hs, js)) / n if n else None
        ok = bool(kappa is not None and icc is not None and kappa >= kappa_gate and icc >= icc_gate)
        result[d] = {"n": n, "pearson": r, "weighted_kappa": kappa, "icc_2_1": icc,
                     "mean_abs_diff": mad, "pass": ok,
                     "disagreements": sorted(
                         [{"sample_id": s, "human": h, "judge": j, "diff": abs(h - j)}
                          for s, h, j in zip(sids, hs, js)],
                         key=lambda x: -x["diff"])[:8]}

    # 写报告
    out = Path(out_dir)
    lines = ["# Judge 校准报告", "",
             f"人工标注文件：`{labels_csv}`  |  judge 结果：`{judged_path}`",
             f"通过门槛：二次加权 kappa ≥ {kappa_gate} 且 ICC(2,1) ≥ {icc_gate}", "",
             "| 维度 | n | Pearson r | 加权 kappa | ICC(2,1) | 平均绝对差 | 判定 |",
             "|---|---|---|---|---|---|---|"]
    for d in CALIB_DIMS:
        v = result[d]
        def f(x):
            return "—" if x is None else f"{x:.3f}"
        lines.append(f"| {DIM_NAMES_CN[d]} | {v['n']} | {f(v['pearson'])} | "
                     f"{f(v['weighted_kappa'])} | {f(v['icc_2_1'])} | {f(v['mean_abs_diff'])} | "
                     f"{'✅ 可用' if v['pass'] else '❌ 需修订'} |")
    lines += ["", "## 判定器能否作为测量工具", ""]
    n_pass = sum(1 for v in result.values() if v["pass"])
    if n_pass == len(CALIB_DIMS):
        lines.append("全部维度通过。可以把 judge 分数用于正式对比（仍需报告人工子样本的一致性）。")
    elif n_pass >= 2:
        lines.append("部分维度通过。**只使用通过维度**做结论；未通过维度需改 rubric / 加锚点示例 / 换 judge 后重新校准。")
    else:
        lines.append("多数维度未通过。**当前 judge 不能用来下结论**，请先修订 rubric（明确锚点、加反例）再标一轮。")
    for d in CALIB_DIMS:
        if result[d]["disagreements"]:
            lines += ["", f"### {DIM_NAMES_CN[d]} 分歧最大样本"]
            lines += ["| sample | 人工 | judge | 差 |", "|---|---|---|---|"]
            for x in result[d]["disagreements"][:5]:
                if x["diff"]:
                    lines.append(f"| {x['sample_id']} | {x['human']} | {x['judge']} | {x['diff']} |")
    (out / "calibration.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "calibration.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[calibrate] 报告：{out/'calibration.md'}")
    return result


# ------------------------------------------------------------------ CLI
def main() -> None:
    ap = argparse.ArgumentParser(description="judge 校准")
    ap.add_argument("--make-template", metavar="JUDGED_JSONL")
    ap.add_argument("--score", metavar="LABELS_CSV")
    ap.add_argument("--judged", default="guide_eval/out/judged.jsonl")
    ap.add_argument("--out-dir", default="guide_eval/out")
    ap.add_argument("--sample-ratio", type=float, default=1.0)
    ap.add_argument("--kappa-gate", type=float, default=0.40)
    ap.add_argument("--icc-gate", type=float, default=0.50)
    args = ap.parse_args()

    if args.make_template:
        make_template(args.make_template, args.out_dir, args.sample_ratio)
    elif args.score:
        score(args.score, args.judged, args.out_dir, args.kappa_gate, args.icc_gate)
    else:
        ap.error("需要 --make-template 或 --score")


if __name__ == "__main__":
    main()
