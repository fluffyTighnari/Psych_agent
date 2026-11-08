# -*- coding: utf-8 -*-
"""引导型咨询有效性评测 · 一键运行入口。

用法：
    python -m guide_eval.run --mock                     # 离线跑通全流程（不需要 API key）
    python -m guide_eval.run --selftest                 # 只验证指标/统计实现
    python -m guide_eval.run --models deepseek-chat \
        --conditions raw,generic,advice,guide_prod --limit-cases 8
    python -m guide_eval.run --judge-only --resume      # 复用已有对话，只重跑判定

产物（默认 guide_eval/out/）：
    transcripts.jsonl  每段对话原文 + 模拟器状态 + 后测
    judged.jsonl       判定器输出（证据编码 + 盲评）
    samples.jsonl      每段对话的指标行
    pairwise.jsonl     成对比较原始结果
    summary.json       聚合结果（机器可读）
    report.md          人类可读报告
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from . import prompts  # noqa: E402
from .generate import format_transcript, load_cases, run_conversation  # noqa: E402
from .judge import judge_conversation, judge_pairwise  # noqa: E402
from .metrics import (  # noqa: E402
    PAIR_KEYS, aggregate, paired_delta, pairwise_summary, score_sample,
)
from .providers import (  # noqa: E402
    MockProvider, ModelSpec, load_env, load_models, make_provider, resolve_models,
)
from .report import render  # noqa: E402

DEFAULT_CONDITIONS = ["raw", "generic", "advice", "guide_prod", "guide_lite"]


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _maybe_load_calibration(out: Path):
    p = out / "calibration.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


# ------------------------------------------------------------------ 主流程
def run(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = load_cases(Path(args.cases), args.limit_cases)
    if args.case_ids:
        want = {x.strip() for x in args.case_ids.split(",") if x.strip()}
        cases = [c for c in cases if c["id"] in want]
        if not cases:
            raise SystemExit(f"[run] --case-ids 没匹配到用例：{args.case_ids}")
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    for c in conditions:
        if c not in prompts.CONDITIONS:
            raise SystemExit(f"未知条件 {c}，可选：{', '.join(prompts.CONDITIONS)}")

    load_env()
    specs, defaults = ([], {}) if args.mock else load_models(Path(args.models_file))
    if args.mock:
        cand_specs = [ModelSpec(name=n, provider="mock", roles=["candidate"])
                      for n in (args.mock_models.split(",") if args.mock_models else ["mock-A", "mock-B"])]
        judge_spec = ModelSpec(name="mock-judge", provider="mock", roles=["judge"])
        sim_spec = ModelSpec(name="mock-sim", provider="mock", roles=["simulator"])
    else:
        by_role = resolve_models(specs, defaults, ["candidate", "judge", "simulator"])
        cand_specs = by_role["candidate"]
        if args.models:
            want = {x.strip() for x in args.models.split(",")}
            cand_specs = [x for x in cand_specs if x.name in want]
            if not cand_specs:
                raise SystemExit(f"[run] --models 没匹配到候选模型：{args.models}")
        judge_spec = by_role["judge"][0]
        sim_spec = by_role["simulator"][0]

    try:
        judge = make_provider(judge_spec)
        simulator = make_provider(sim_spec)
        candidates = []
        for spec in cand_specs:
            try:
                candidates.append((spec.name, make_provider(spec)))
            except Exception as e:
                print(f"[run] 跳过候选模型 {spec.name}: {e}")
        if not candidates:
            raise SystemExit("[run] 没有可用的候选模型；先用 --mock 验证，或检查 models.json/.env")
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(f"[run] 模型初始化失败: {e}")

    print(f"[run] cases={len(cases)} conditions={conditions} candidates={[n for n,_ in candidates]}")
    print(f"[run] judge={judge_spec.name} simulator={sim_spec.name} max_turns={args.max_turns}")

    transcripts_path = out / "transcripts.jsonl"
    judged_path = out / "judged.jsonl"
    samples_path = out / "samples.jsonl"
    pairwise_path = out / "pairwise.jsonl"

    existing = {(r["model"], r["condition"], r["case_id"]) for r in _read_jsonl(transcripts_path)}
    transcripts = _read_jsonl(transcripts_path)
    t0 = time.time()
    n_gen = 0
    write_lock = threading.Lock()

    def _gen_one(task):
        case, cond, model_name, provider = task
        tr = run_conversation(case, cond, provider, simulator, max_turns=args.max_turns)
        tr["model"] = model_name
        tr["transcript"] = format_transcript(tr["conv"])
        with write_lock:
            _append_jsonl(transcripts_path, tr)
            transcripts.append(tr)
        print(f"  [gen] {case['id']} | {cond:10s} | {model_name:18s} "
              f"turns={len(tr['turns'])} ended={tr['ended']} err={tr['error'][:40]}")
        return tr

    if args.judge_only:
        if not transcripts:
            raise SystemExit(f"[run] --judge-only 需要已有 {transcripts_path}；先跑一次生成")
        print(f"[run] --judge-only：复用 {len(transcripts)} 段已生成对话，跳过生成")
    else:
        tasks = [(case, cond, name, prov) for case in cases for cond in conditions
                 for name, prov in candidates
                 if not (args.resume and (name, cond, case["id"]) in existing)]
        print(f"[run] 待生成 {len(tasks)} 段对话，并发 {args.concurrency}")
        if args.concurrency <= 1:
            for t in tasks:
                _gen_one(t)
                n_gen += 1
        else:
            with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
                futs = [ex.submit(_gen_one, t) for t in tasks]
                for f in as_completed(futs):
                    try:
                        f.result()
                        n_gen += 1
                    except Exception as e:
                        print(f"  [gen] 失败: {e}")

    # ---------------- 判定
    if not args.gen_only:
        judged_keys = {(r["model"], r["condition"], r["case_id"]) for r in _read_jsonl(judged_path)}
        judged_rows = _read_jsonl(judged_path)
        case_by_id = {c["id"]: c for c in cases}

        def _judge_one(tr):
            key = (tr["model"], tr["condition"], tr["case_id"])
            case = case_by_id.get(tr["case_id"])
            if not case:
                return None
            judged = judge_conversation(judge, case, tr["conv"])
            row = {"model": tr["model"], "condition": tr["condition"], "case_id": tr["case_id"],
                   "transcript": tr["transcript"], **judged}
            with write_lock:
                _append_jsonl(judged_path, row)
                judged_rows.append(row)
            print(f"  [judge] {tr['case_id']} | {tr['condition']:10s} | {tr['model']}")
            return row

        pending = [tr for tr in transcripts
                   if not (args.resume and (tr["model"], tr["condition"], tr["case_id"]) in judged_keys)]
        print(f"[run] 待判定 {len(pending)} 段，并发 {args.concurrency}")
        if args.concurrency <= 1:
            for tr in pending:
                try:
                    _judge_one(tr)
                except Exception as e:
                    print(f"  [judge] 失败 {tr['model']}/{tr['condition']}/{tr['case_id']}: {e}")
        else:
            with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
                futs = [ex.submit(_judge_one, tr) for tr in pending]
                for f in as_completed(futs):
                    try:
                        f.result()
                    except Exception as e:
                        print(f"  [judge] 失败: {e}")

        # ---------------- 指标
        judge_by_key = {(r["model"], r["condition"], r["case_id"]): r for r in judged_rows}
        records = []
        for tr in transcripts:
            jr = judge_by_key.get((tr["model"], tr["condition"], tr["case_id"]))
            if not jr:
                continue
            records.append(score_sample(tr, jr))
        with open(samples_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        # ---------------- 成对比较
        pairwise = {}
        if args.pairwise:
            target, baseline = "guide_prod", "advice"
            tr_by = {(t["model"], t["condition"], t["case_id"]): t for t in transcripts}
            pairs = []

            def _pair_one(tr):
                b = tr_by.get((tr["model"], baseline, tr["case_id"]))
                if not b:
                    return None
                w1 = judge_pairwise(judge, tr["conv"], b["conv"])      # A=target
                w2 = judge_pairwise(judge, b["conv"], tr["conv"])      # A=baseline
                row = {"case_id": tr["case_id"], "model": tr["model"],
                       "cond_a": target, "cond_b": baseline,
                       "winner_raw": w1["winner"], "winner_swapped": w2["winner"],
                       "confidence": min(w1["confidence"], w2["confidence"]),
                       "key_difference": w1["key_difference"]}
                with write_lock:
                    pairs.append(row)
                    _append_jsonl(pairwise_path, row)
                return row

            pair_tasks = [tr for tr in transcripts if tr["condition"] == target]
            if args.concurrency <= 1:
                for tr in pair_tasks:
                    try:
                        _pair_one(tr)
                    except Exception as e:
                        print(f"  [pairwise] 失败 {tr['case_id']}: {e}")
            else:
                with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
                    futs = [ex.submit(_pair_one, tr) for tr in pair_tasks]
                    for f in as_completed(futs):
                        try:
                            f.result()
                        except Exception as e:
                            print(f"  [pairwise] 失败: {e}")
            pairwise = pairwise_summary(pairs) if pairs else {}

        # ---------------- 聚合 + 报告
        agg = aggregate(records)
        paired = []
        if {"guide_prod", "advice"} <= {r["condition"] for r in records}:
            paired = [paired_delta(records, "guide_prod", "advice", k) for k in PAIR_KEYS]
        provider_map = {}
        for name, prov in candidates:
            provider_map[name] = getattr(getattr(prov, "spec", None), "provider", "")
        cli_models = [n for n, p in provider_map.items() if p == "cli"]
        meta = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "n_cases": len({r["case_id"] for r in records}),
            "n_models": len({r["model"] for r in records}),
            "max_turns": args.max_turns,
            "judge": judge_spec.name,
            "simulator": sim_spec.name,
            "conditions": conditions,
            "mock": args.mock,
            "providers": provider_map,
            "cli_models": cli_models,
            "concurrency": args.concurrency,
            "elapsed_sec": round(time.time() - t0, 1),
        }
        calibration = _maybe_load_calibration(out)
        text = render(agg, records, paired, pairwise, meta, out / "report.md", calibration)
        (out / "summary.json").write_text(json.dumps(
            {"meta": meta, "aggregate": agg, "paired": paired, "pairwise": pairwise},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n[run] 完成：{len(records)} 条样本，{meta['elapsed_sec']}s")
        print(f"[run] 报告：{out/'report.md'}")
        print("[run] 提醒：正式结论前先跑 calibrate.py 做人工校准。")
    else:
        print(f"\n[run] 只生成对话：{n_gen} 条，写入 {transcripts_path}")


# ------------------------------------------------------------------ selftest
def selftest() -> None:
    """用合成数据验证指标/统计/成对比较的实现。"""
    from .metrics import bootstrap_ci, cohens_dz, mean

    assert mean([1, 2, 3]) == 2
    lo, hi = bootstrap_ci([1.0, 2, 3, 4, 5])
    assert lo is not None and hi is not None and lo <= 3 <= hi
    assert cohens_dz([1, 1, 1]) is None or cohens_dz([1, 1, 1]) > 0

    base = {
        "n_turns": 4, "n_user_turns": 4, "ended": False, "error": "",
        "question_rate": 0.5, "questions_per_turn": 1.0, "advice_turn_rate": 0.0,
        "solution_turn_rate": 0.0, "avg_chars": 100, "n_gold": 2, "n_surfaced": 1,
        "recall": 0.5, "precision": 0.5, "f1": 0.5, "extra_claims": 1,
        "l2_inquiry_rate": 1.0, "l3_self_explain_rate": 1.0, "full_chain_rate": 0.5,
        "resolved_rate": 0.0, "turns_to_surface": 2, "premature_solution": False,
        "user_self_explain_density": 2.0, "rb_mean": 4.0, "fatal_flaw": False,
        "clarity": 7, "insight": 2, "autonomy": 8, "action_intent": 7,
        "alliance": 7, "pressure": 2, "safety_needed": False, "safety_performed": False,
        "safety_referred": False,
    }
    for k in ["contradiction_accuracy", "depth", "question_fit", "autonomy_support",
              "progression", "empathy_safety", "self_explanation_elicitation",
              "overall_effectiveness"]:
        base[f"rb_{k}"] = 4

    def rec(cond, model, case, **over):
        r = dict(base, condition=cond, model=model, case_id=case)
        r.update(over)
        return r

    records = [
        rec("guide_prod", "m1", "c01", full_chain_rate=0.8, rb_mean=4.2, autonomy=8),
        rec("advice", "m1", "c01", full_chain_rate=0.2, rb_mean=3.0, autonomy=4),
        rec("guide_prod", "m1", "c02", full_chain_rate=0.6, rb_mean=4.0, autonomy=7),
        rec("advice", "m1", "c02", full_chain_rate=0.3, rb_mean=3.2, autonomy=5),
        rec("guide_prod", "m2", "c01", full_chain_rate=0.4, rb_mean=3.5, autonomy=6),
        rec("advice", "m2", "c01", full_chain_rate=0.5, rb_mean=3.8, autonomy=6),
    ]
    agg = aggregate(records)
    assert agg["by_condition"]["guide_prod"]["n"] == 3
    assert abs(agg["by_condition"]["guide_prod"]["full_chain_rate"] - 0.6) < 1e-9
    d = paired_delta(records, "guide_prod", "advice", "full_chain_rate")
    assert d["n_pairs"] == 3 and d["delta"] is not None
    # 三条配对差：0.6, 0.3, -0.1 → 0.2667
    assert abs(d["delta"] - (0.6 + 0.3 - 0.1) / 3) < 1e-9

    pairs = [
        {"cond_a": "guide_prod", "cond_b": "advice", "winner_raw": "A", "winner_swapped": "B"},
        {"cond_a": "guide_prod", "cond_b": "advice", "winner_raw": "A", "winner_swapped": "A"},
        {"cond_a": "guide_prod", "cond_b": "advice", "winner_raw": "TIE", "winner_swapped": "TIE"},
    ]
    ps = pairwise_summary(pairs)
    assert ps["n"] == 3
    assert abs(ps["stable_win_a"] - 1 / 3) < 1e-9
    assert abs(ps["position_unstable"] - 1 / 3) < 1e-9

    # 加权 kappa 完全一致 = 1
    from .calibrate import quadratic_weighted_kappa
    assert abs(quadratic_weighted_kappa([1, 2, 3], [1, 2, 3]) - 1.0) < 1e-9
    print("[selftest] ✅ 指标/统计/校准函数全部通过")


# ------------------------------------------------------------------ CLI
def main() -> None:
    ap = argparse.ArgumentParser(description="引导型咨询有效性评测")
    ap.add_argument("--mock", action="store_true", help="用 mock 模型离线跑通流水线")
    ap.add_argument("--selftest", action="store_true", help="只验证指标实现")
    ap.add_argument("--models-file", default=str(HERE / "models.json"))
    ap.add_argument("--cases", default=str(HERE / "cases.json"))
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--limit-cases", type=int, default=None)
    ap.add_argument("--case-ids", default="", help="只跑指定用例 id，逗号分隔，如 c01,c02,c10")
    ap.add_argument("--max-turns", type=int, default=5)
    ap.add_argument("--conditions", default=",".join(DEFAULT_CONDITIONS))
    ap.add_argument("--models", default="", help="真实模式下的候选模型名，逗号分隔")
    ap.add_argument("--mock-models", default="mock-A,mock-B", help="mock 模式下的候选名")
    ap.add_argument("--no-pairwise", dest="pairwise", action="store_false")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--gen-only", action="store_true", help="只生成对话，不判定")
    ap.add_argument("--judge-only", action="store_true", help="跳过生成（配合 --resume）")
    ap.add_argument("--concurrency", type=int, default=4, help="并发请求数（推理模型建议 4-8）")
    ap.set_defaults(pairwise=True)
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    if args.mock:
        args.limit_cases = args.limit_cases or 4
        args.max_turns = args.max_turns or 4
    run(args)


if __name__ == "__main__":
    main()
