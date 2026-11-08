# -*- coding: utf-8 -*-
"""固定脚本对话评测（简化版）。

流程：
  1. 读 script.json 的 8 轮用户话术（所有模型完全一致，不随回复变化）；
  2. 依次把每轮用户消息发给每个模型，记录完整回复；
  3. 每个模型写一个 results/<model>.md / .json；
  4. 用**规则关键词**算硬指标（矛盾发现轮次、组件覆盖、问句率、建议率、过早给方案等）；
  5. 生成 metrics.csv / report.md 和人工盲评模板 human_review.csv。

用法：
  caffeinate -i python -m guide_eval.scripted.run
  python -m guide_eval.scripted.run --models deepseek-v4.1-flash,kimi-k3 --concurrency 4
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guide_eval.providers import ModelSpec, load_env, make_provider  # noqa: E402

BASE_URL = "https://opencode.ai/zen/go/v1"
KEY_ENV = "OPENCODE_GO_API_KEY"
HEADERS = {"x-opencode-session": "guide-eval-scripted"}

# 只放实测可用的 chat/completions 模型（go 套餐）
DEFAULT_MODELS = [
    ("deepseek-v4.1-flash", "deepseek-v4.1-flash"),
    ("glm-5.3-flash", "glm-5.3-flash"),
    ("kimi-k3", "kimi-k3"),
    ("qwen3.8-flash", "qwen3.8-flash"),
    ("longcat-2.0", "longcat-2.0"),
    ("hy3", "hy3"),
    ("mimo-v2.6-flash", "mimo-v2.6-flash"),
]

ADVICE_MARKERS = ["建议你", "你应该", "你需要", "你必须", "可以试试", "不妨", "第一步",
                  "第二步", "具体做法", "给你一个", "给你三个", "给你两个", "给你几个",
                  "分步骤", "行动方案", "我的建议", "做一件事", "做三件事", "做两件事",
                  "试试看", "你可以先", "先做一件", "要不要考虑", "实验", "这周", "这个月"]
_LIST_RE = re.compile(r"(?:^|\n)\s*(?:#{1,4}\s*)?(?:[1-9][\.、）)]|第[一二三四五][，,、])")
_SENT_RE = re.compile(r"[。！？!?；;\n]+")
DIRECTIVE_MARKERS = ["你应该", "你需要", "你必须", "建议你", "你要", "应该先", "得先"]
OPEN_Q_MARKERS = ["什么", "怎么", "为什么", "如何", "哪些", "哪一", "如果", "愿不愿意",
                  "能不能", "可不可以", "什么样", "多久", "哪一刻", "哪件事", "会怎样"]
EMPATHY_MARKERS = ["听起来", "我听到", "你感到", "我理解", "理解你", "难受", "辛苦",
                   "不容易", "抱抱", "被卡住", "很煎熬", "很累"]


def safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in s)


def load_script(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_spec(name: str, model_id: str, max_tokens: int = 2000,
               temperature: float = 0.3, timeout: float = 200.0) -> ModelSpec:
    return ModelSpec(
        name=name, provider="openai", model=model_id, base_url=BASE_URL,
        api_key_env=KEY_ENV, temperature=temperature, max_tokens=max_tokens,
        timeout=timeout, extra_headers=dict(HEADERS), roles=["candidate"],
    )


# ------------------------------------------------------------------ 规则判定
def _has_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def match_component(text: str, spec: dict) -> bool:
    """句级匹配：同一句里满足 all 的每组 + any 的至少一组，才算命中。

    句级（而不是整段）匹配能显著减少“只要提到过就算”的假阳性。
    """
    for sent in _SENT_RE.split(text):
        if not sent.strip():
            continue
        ok = True
        for group in spec.get("all", []):
            if not _has_any(sent, group):
                ok = False
                break
        if not ok:
            continue
        any_groups = spec.get("any", [])
        if any_groups and not any(_has_any(sent, g) for g in any_groups):
            continue
        context = spec.get("context", [])
        if context and not _has_any(sent, context):
            continue
        return True
    return False


def looks_like_advice(text: str) -> bool:
    return _has_any(text, ADVICE_MARKERS) or bool(_LIST_RE.search(text))


def analyze_turn(text: str, patterns: dict) -> dict:
    comps = [key for key, spec in patterns.items() if match_component(text, spec)]
    central = any(k in ("A_action_vs_word", "B_fear_of_failure", "D_parents_expectation") for k in comps)
    qmarks = text.count("？") + text.count("?")
    q = qmarks > 0
    advice = looks_like_advice(text)
    return {
        "chars": len(text),
        "has_question": q,
        "qmarks": qmarks,
        "open_question": q and _has_any(text, OPEN_Q_MARKERS),
        "advice": advice,
        "directives": sum(text.count(w) for w in DIRECTIVE_MARKERS),
        "empathy": _has_any(text, EMPATHY_MARKERS),
        "components": comps,
        "central_named": central,
    }


def summarize(turns: list[dict], patterns: dict) -> dict:
    n = len(turns)
    comps_ever = {k: any(k in t["analysis"]["components"] for t in turns) for k in patterns}
    first_central = next((t["turn"] for t in turns if t["analysis"]["central_named"]), None)
    first_advice = next((t["turn"] for t in turns if t["analysis"]["advice"]), None)
    q_turns = sum(1 for t in turns if t["analysis"]["has_question"])
    open_q = sum(1 for t in turns if t["analysis"]["open_question"])
    advice_turns = sum(1 for t in turns if t["analysis"]["advice"])
    total_chars = sum(t["analysis"]["chars"] for t in turns)
    directives = sum(t["analysis"]["directives"] for t in turns)
    last = turns[-1]["analysis"] if turns else {}
    premature = bool(first_advice is not None and (first_central is None or first_advice < first_central))
    return {
        "n_turns": n,
        "question_turns": q_turns,
        "question_rate": round(q_turns / n, 3) if n else None,
        "questions_per_turn": round(sum(t["analysis"]["qmarks"] for t in turns) / n, 2) if n else None,
        "open_question_ratio": round(open_q / q_turns, 3) if q_turns else None,
        "advice_turns": advice_turns,
        "advice_turn_rate": round(advice_turns / n, 3) if n else None,
        "first_contradiction_turn": first_central,
        "named_before_turn7": bool(first_central is not None and first_central <= 6),
        "premature_solution": premature,
        "first_advice_turn": first_advice,
        "components_ever": comps_ever,
        "component_coverage": round(sum(comps_ever.values()) / len(comps_ever), 3) if comps_ever else None,
        "directive_per_1k_chars": round(directives / total_chars * 1000, 2) if total_chars else None,
        "avg_chars": round(total_chars / n, 1) if n else None,
        "total_chars": total_chars,
        "empathy_rate": round(sum(1 for t in turns if t["analysis"]["empathy"]) / n, 3) if n else None,
        "ends_with_plan": bool(last.get("advice")),
        "ends_with_question": bool(last.get("has_question")),
    }


# ------------------------------------------------------------------ 单模型
def run_model(name: str, model_id: str, script: dict, out_dir: Path,
              max_tokens: int) -> dict:
    spec = build_spec(name, model_id, max_tokens=max_tokens)
    provider = make_provider(spec)
    patterns = script["detect_patterns"]
    turns = []
    error = ""
    t0 = time.time()
    for i, user_msg in enumerate(script["user_turns"], 1):
        msgs = [{"role": "user" if j % 2 == 0 else "assistant", "content": m}
                for j, m in enumerate(turns_msg(turns))]
        msgs.append({"role": "user", "content": user_msg})
        try:
            try:
                reply = provider.chat(msgs, temperature=0.3)
            except Exception:
                time.sleep(2)
                reply = provider.chat(msgs, temperature=0.3, max_tokens=min(8000, max_tokens * 2))
        except Exception as e:
            error = f"turn {i} error: {e}"
            turns.append({"turn": i, "user": user_msg, "reply": "", "error": str(e),
                          "analysis": analyze_turn("", patterns)})
            break
        turns.append({"turn": i, "user": user_msg, "reply": reply,
                      "analysis": analyze_turn(reply, patterns)})
        print(f"  [{name}] turn {i}/{len(script['user_turns'])} "
              f"q={'Y' if turns[-1]['analysis']['has_question'] else 'n'} "
              f"adv={'Y' if turns[-1]['analysis']['advice'] else 'n'} "
              f"central={'Y' if turns[-1]['analysis']['central_named'] else 'n'}", flush=True)
    summary = summarize(turns, patterns)
    summary.update({"model": name, "model_id": model_id, "error": error,
                    "elapsed_sec": round(time.time() - t0, 1)})
    # 每模型一个文件
    (out_dir / "results").mkdir(parents=True, exist_ok=True)
    (out_dir / "results" / f"{safe_name(name)}.json").write_text(
        json.dumps({"summary": summary, "turns": turns}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (out_dir / "results" / f"{safe_name(name)}.md").write_text(
        render_model_md(script, summary, turns), encoding="utf-8")
    return summary


def turns_msg(turns: list[dict]) -> list[str]:
    """把已生成的回合展开成 [user, assistant, user, assistant...]。"""
    out = []
    for t in turns:
        out.append(t["user"])
        out.append(t["reply"])
    return out


def render_model_md(script: dict, summary: dict, turns: list[dict]) -> str:
    L = [f"# {summary['model']}", "",
         f"- 模型 ID：`{summary['model_id']}` ｜ 轮数：{summary['n_turns']} ｜ 耗时：{summary['elapsed_sec']}s",
         f"- 首破轮次：{summary['first_contradiction_turn']} ｜ 第 7 轮前点破：{summary['named_before_turn7']} "
         f"｜ 组件覆盖：{sum(summary['components_ever'].values())}/4 ｜ 过早给方案：{summary['premature_solution']}",
         ""]
    if summary.get("error"):
        L += [f"> ⚠️ {summary['error']}", ""]
    for t in turns:
        a = t["analysis"]
        tags = []
        if a["central_named"]:
            tags.append("**点破矛盾**")
        if a["components"]:
            tags.append("组件:" + ",".join(a["components"]))
        if a["has_question"]:
            tags.append(f"问句x{a['qmarks']}")
        if a["advice"]:
            tags.append("给建议")
        L += [f"## 第 {t['turn']} 轮", "", f"**用户：** {t['user']}", "",
              f"**{summary['model']}：** {t['reply'] or '（无输出）'}", "",
              f"*（{ '，'.join(tags) if tags else '无标签' }｜{a['chars']} 字）*", ""]
    return "\n".join(L)



def reanalyze(out: Path, script: dict) -> list[dict]:
    """不调用模型，只用新规则重算已有 results/*.json 的硬指标。"""
    pats = script["detect_patterns"]
    summaries = []
    for f in sorted((out / "results").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        turns = d.get("turns", [])
        for t in turns:
            t["analysis"] = analyze_turn(t.get("reply", ""), pats)
        s = summarize(turns, pats)
        s.update({"model": d["summary"]["model"], "model_id": d["summary"].get("model_id", ""),
                  "error": d["summary"].get("error", ""), "elapsed_sec": d["summary"].get("elapsed_sec")})
        summaries.append(s)
        f.write_text(json.dumps({"summary": s, "turns": turns}, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "results" / f"{safe_name(s['model'])}.md").write_text(
            render_model_md(script, s, turns), encoding="utf-8")
    render_report(summaries, script, out)
    write_tables(summaries, out, script)
    print(f"[reanalyze] 重算 {len(summaries)} 个模型 → {out/'report.md'}")
    return summaries


# ------------------------------------------------------------------ 报告
MAIN_COLS = [
    ("first_contradiction_turn", "首破轮次"),
    ("named_before_turn7", "第7轮前点破"),
    ("component_coverage", "组件覆盖"),
    ("question_rate", "问句轮占比"),
    ("questions_per_turn", "每轮问号"),
    ("advice_turn_rate", "建议轮占比"),
    ("premature_solution", "过早给方案"),
    ("directive_per_1k_chars", "指令密度/千字"),
    ("avg_chars", "平均字数"),
    ("ends_with_plan", "结尾给方案"),
    ("ends_with_question", "结尾仍在提问"),
]


def fmt(v):
    if isinstance(v, bool):
        return "✅" if v else "❌"
    if isinstance(v, float):
        return f"{v:.2f}"
    if v is None:
        return "—"
    return str(v)


def render_report(summaries: list[dict], script: dict, out: Path) -> str:
    summaries = sorted(summaries, key=lambda s: (s["component_coverage"] or 0,
                                                 -(s["first_contradiction_turn"] or 99)), reverse=True)
    L = ["# 固定脚本对话 · 硬指标报告", "",
         f"- 用例：{script['title']}",
         f"- 用户轮数：{len(script['user_turns'])}；模型数：{len(summaries)}",
         "- 说明：以下为**关键词规则**算出的硬指标，用于快速筛查，不替代人工评分。",
         ""]
    L.append("| 模型 | " + " | ".join(c[1] for c in MAIN_COLS) + " |")
    L.append("|---|" + "---|" * len(MAIN_COLS))
    for s in summaries:
        L.append(f"| {s['model']} | " + " | ".join(fmt(s.get(k)) for k, _ in MAIN_COLS) + " |")
    L += ["", "## 组件明细（A=言行矛盾 B=失败恐惧 C=拖延缓冲 D=父母期待）", "",
          "| 模型 | A | B | C | D |", "|---|---|---|---|---|"]
    for s in summaries:
        c = s["components_ever"]
        L.append(f"| {s['model']} | " + " | ".join("✅" if c.get(k) else "—" for k in
                                                   ["A_action_vs_word", "B_fear_of_failure",
                                                    "C_procrastination_as_shield", "D_parents_expectation"]) + " |")
    L += ["", "## 判读提示", "",
          "- **第7轮前点破**是核心差异：第 7 轮用户自己说出了“怕失败=证明我不行”，越晚点破说明引导越被动。",
          "- **组件覆盖**只说明“有没有提到”，不说明“提得准不准、有没有编造”，必须结合人工评分。",
          "- **问句轮占比**要与**建议轮占比**一起看：纯问句但模板化，不等于好引导。",
          "- **结尾给方案**：第 8 轮用户直接问“我该怎么办”，此时是否守住引导、把判断权留给用户，是引导型的关键测试点。",
          "- 人工评分请用 `human_review.csv`（已做盲评编号），填完交回后再算一致性并与硬指标对照。", ""]
    text = "\n".join(L)
    (out / "report.md").write_text(text, encoding="utf-8")
    return text


def write_tables(summaries: list[dict], out: Path, script: dict) -> None:
    # 硬指标 CSV
    keys = list(dict.fromkeys([k for k, _ in MAIN_COLS] + ["component_coverage", "empathy_rate", "error"]))
    with open(out / "metrics.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", *keys])
        for s in summaries:
            row = [s["model"]]
            for k in keys:
                v = s.get(k)
                row.append(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
            w.writerow(row)
    (out / "metrics.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf-8")

    # 人工盲评模板（打乱顺序、匿名编号、匿名 transcript）
    order = sorted(summaries, key=lambda s: s["model"])
    import random
    rng = random.Random(42)
    rng.shuffle(order)
    review_dir = out / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    blind = {}
    rows = []
    dims = ["contradiction_accuracy", "depth", "autonomy_support", "question_fit", "overall_effectiveness"]
    for i, s in enumerate(order, 1):
        bid = f"M{i:02d}"
        blind[bid] = s["model"]
        # 匿名副本：去掉模型名/模型 ID/统计头，只留对话
        data = json.loads((out / "results" / f"{safe_name(s['model'])}.json").read_text(encoding="utf-8"))
        lines = [f"# 对话 {bid}（8 轮）", ""]
        for t in data["turns"]:
            reply = t["reply"].replace(s["model"], "模型").replace(s.get("model_id", ""), "模型")
            lines += [f"**用户：** {t['user']}", "", f"**模型：** {reply}", ""]
        (review_dir / f"{bid}.md").write_text("\n".join(lines), encoding="utf-8")
        rows.append({"blind_id": bid, "transcript_file": f"review/{bid}.md",
                     **{d: "" for d in dims}, "note": ""})
    with open(out / "human_review.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["blind_id", "transcript_file", *dims, "note"])
        w.writeheader()
        w.writerows(rows)
    (out / "blind_key.json").write_text(json.dumps(blind, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "human_review_guide.md").write_text(
        "# 人工盲评说明\n\n"
        "请打开 `human_review.csv`，按 `transcript_file` 逐个阅读对话，给 5 个维度打 1-5 分"
        "（1=最差，5=最好）。不要打开 `blind_key.json`，不要根据文件名猜模型。\n\n"
        "- 矛盾发现准确性：是否点出真实矛盾，且无编造\n"
        "- 引导深度：是否触及核心恐惧/价值冲突，而非停在表面\n"
        "- 自主性支持：是否把判断权留给用户，而非给方案/下结论\n"
        "- 提问贴合度：问题是否建立在用户刚说的内容上\n"
        "- 总体引导有效性：综合看是否帮用户更清楚并形成自己的判断\n\n"
        "评分标准可参考 `../../RATING_GUIDE.md`。填好后把 `human_review.csv` 交回，"
        "我会计算模型间差异、与硬指标的相关性，以及（如果多人评）评分者一致性。\n",
        encoding="utf-8")


# ------------------------------------------------------------------ CLI
def main() -> None:
    ap = argparse.ArgumentParser(description="固定脚本对话硬指标评测")
    ap.add_argument("--models", default="", help="逗号分隔的模型名，默认 7 个")
    ap.add_argument("--concurrency", type=int, default=7)
    ap.add_argument("--max-tokens", type=int, default=2000)
    ap.add_argument("--out", default=str(HERE))
    ap.add_argument("--resume", action="store_true", help="跳过已有 results/<model>.json")
    ap.add_argument("--reanalyze", action="store_true", help="不调用模型，只用新规则重算已有结果")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    script = load_script(HERE / "script.json")
    if args.reanalyze:
        reanalyze(out, script)
        return
    load_env()

    wanted = set(x.strip() for x in args.models.split(",") if x.strip())
    models = [(n, m) for n, m in DEFAULT_MODELS if not wanted or n in wanted]
    if not models:
        raise SystemExit(f"--models 没匹配到：{args.models}")

    if args.resume:
        models = [(n, m) for n, m in models if not (out / "results" / f"{safe_name(n)}.json").exists()]

    if not os.getenv(KEY_ENV):
        raise SystemExit(f"缺少环境变量 {KEY_ENV}（在 .env 中配置）")

    print(f"[scripted] 模型 {len(models)} 个 × 用户轮数 {len(script['user_turns'])}，并发 {args.concurrency}")
    summaries = []
    lock = threading.Lock()

    def task(item):
        name, mid = item
        s = run_model(name, mid, script, out, args.max_tokens)
        with lock:
            summaries.append(s)
        return s

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(task, it) for it in models]
        for f in as_completed(futs):
            try:
                s = f.result()
                print(f"[done] {s['model']}  首破={s['first_contradiction_turn']} "
                      f"组件={sum(s['components_ever'].values())}/4 过早方案={s['premature_solution']}", flush=True)
            except Exception as e:
                print(f"[fail] {e}")

    # 合并已有结果（resume 时）
    existing = []
    for f in (out / "results").glob("*.json"):
        try:
            existing.append(json.loads(f.read_text(encoding="utf-8"))["summary"])
        except Exception:
            pass
    merged = {s["model"]: s for s in existing}
    merged.update({s["model"]: s for s in summaries})
    all_summ = list(merged.values())

    render_report(all_summ, script, out)
    write_tables(all_summ, out, script)
    print(f"\n[scripted] 完成 {len(all_summ)} 个模型，{round(time.time() - t0, 1)}s")
    print(f"[scripted] 报告：{out/'report.md'}")
    print(f"[scripted] 每模型记录：{out/'results'}/<model>.md")
    print(f"[scripted] 人工盲评：{out/'human_review.csv'}（填完交回）")


if __name__ == "__main__":
    main()
