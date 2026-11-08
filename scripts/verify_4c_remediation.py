#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""阶段 4-C 独立验签：decompose_query / evidence_gap / CRAG 一次性补救。

用法（仓库根目录）：
    $env:PYTHONIOENCODING="utf-8"; python scripts/verify_4c_remediation.py

覆盖：
A. 导入顺序（core.tools.registry 与 core.orchestrator.remediation 双向无环）
B. _extract_json_array / decompose_query 的边界与兜底
C. evaluate_evidence 的四档判决（empty / weak / no_principle / ok）与「取最高分」
D. evaluate_step 的优先级（failure > evidence_gap > success）
E. merge_evidence / retrieve_multi 的合并去重
F. remediate_once 的硬预算与「只补一次」
G. 真实 RetrievalPipeline 的 score_map 与 doc 顺序（与 run().final 逐条一致）

只读业务数据（data/、store/），不写任何业务文件；退出码 0=PASS，1=FAIL。
"""
from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

RESULTS = []


def check(name: str, fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"[FAIL] {name} -> {type(exc).__name__}: {exc}")
    else:
        RESULTS.append((name, True, ""))
        print(f"[PASS] {name}")


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def doc(doc_id: str, doc_type: str):
    return SimpleNamespace(doc_id=doc_id, doc_type=doc_type)


# ---------------------------------------------------------------- A 导入顺序
def test_import_orders():
    for mod in ("core.tools.registry", "core.orchestrator.remediation"):
        code = f"import {mod}; print('ok')"
        proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                              capture_output=True, text=True, timeout=120)
        expect(proc.returncode == 0,
               f"{mod} 独立导入失败: {proc.stdout[-300:]} {proc.stderr[-600:]}")


# ---------------------------------------------------------------- B decompose
class StubLLM:
    def __init__(self, reply=None, boom=False):
        self.reply = reply
        self.boom = boom
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        if self.boom:
            raise RuntimeError("stub llm down")
        return self.reply or "[]"


def test_decompose():
    from core.tools.primitives import _extract_json_array, decompose_query
    from core.helper import retrieval_config as RC

    expect(_extract_json_array('```json\n["a","b"]\n```') == ["a", "b"], "代码块数组解析失败")
    expect(_extract_json_array('前缀 ["a", "b"] 后缀') == ["a", "b"], "前缀包裹数组解析失败")
    expect(_extract_json_array("没有数组") is None, "非数组应返回 None")
    expect(_extract_json_array('{"a":1}') is None, "对象应返回 None")

    problem = "我发现自己很容易在人际交往后反复回放和自责。上次聊天时我为了显得务实，直接跳过了对方情绪化的表达。"
    llm = StubLLM('["人际交往后反复回放和自责", "跳过对方情绪只谈解决问题", "如何停止事后反复内疚的内耗"]')
    out = decompose_query(problem, llm=llm)
    expect(out[0] == problem, "第一条必须是原问题")
    expect(len(out) == 3, f"应保留 2 条子查询，实际 {len(out)}: {out}")
    expect(llm.calls and "【具体情境】" not in llm.calls[0][1]["content"], "情境不应进入分解 prompt")

    # 情境剥离 + 过短过滤 + 包含去重 + 数量封顶
    p2 = "我每次和人说话后都会反复自责" + "【具体情境】当时在会议室"
    llm2 = StubLLM('["我每次和人说话后都会反复自责", "我每次和人说话后都会反复自责的延伸句子", "太短", "另一个完全不同方面的应对办法"]')
    out2 = decompose_query(p2, llm=llm2, max_queries=3)
    expect(out2[0] == "我每次和人说话后都会反复自责", f"应剥离情境: {out2}")
    expect(len(out2) <= 3, f"数量应封顶: {out2}")

    # LLM 异常 / 非数组 / 过短 / 空输入
    expect(decompose_query(problem, llm=StubLLM(boom=True)) == [problem], "LLM 异常应退回单查询")
    expect(decompose_query(problem, llm=StubLLM("不是数组")) == [problem], "非数组应退回单查询")
    expect(decompose_query("我很难受", llm=StubLLM('["不应被使用"]')) == ["我很难受"], "短问题不应分解")
    expect(decompose_query("", llm=StubLLM()) == [], "空问题应返回空列表")
    expect(RC.REMEDIATION_MAX_QUERIES == 3, "补救查询上限应为 3（含原查询）")


# ---------------------------------------------------------------- C evidence
def test_evaluate_evidence():
    from core.orchestrator.evaluator import (
        evaluate_evidence, EVIDENCE_GAP, SUCCESS,
        GAP_EMPTY, GAP_WEAK, GAP_NO_PRINCIPLE,
    )
    from core.helper import retrieval_config as RC

    r = evaluate_evidence([], {}, query="我该怎么办")
    expect(r["status"] == EVIDENCE_GAP and r["reason"] == GAP_EMPTY, f"empty 判决错误: {r}")

    docs = [doc("d1", "daily"), doc("d2", "daily")]
    r = evaluate_evidence(docs, {"d1": 0.03, "d2": 0.01}, query="我很内耗")
    expect(r["status"] == EVIDENCE_GAP and r["reason"] == GAP_WEAK, f"weak 判决错误: {r}")
    expect(r["top_score"] == 0.03, f"top_score 应取最高分: {r}")

    # 分数倒挂：第一条 0.04、第二条 0.25 → 仍应判 ok（证明用 max 而非首条）
    r = evaluate_evidence(docs, {"d1": 0.04, "d2": 0.25}, query="我很内耗")
    expect(r["status"] == SUCCESS, f"应取最高分判 ok: {r}")

    r = evaluate_evidence(docs, {"d1": 0.5, "d2": 0.4}, query="我该怎么练习接住情绪")
    expect(r["status"] == EVIDENCE_GAP and r["reason"] == GAP_NO_PRINCIPLE,
           f"no_principle 判决错误: {r}")

    docs_w = docs + [doc("w1", "weekly")]
    r = evaluate_evidence(docs_w, {"d1": 0.5, "d2": 0.4, "w1": 0.6}, query="我该怎么练习接住情绪")
    expect(r["status"] == SUCCESS and r["n_principle"] == 1, f"有周记应 ok: {r}")

    # 无分数时跳过 weak 判定
    r = evaluate_evidence(docs, None, query="我很内耗")
    expect(r["status"] == SUCCESS, f"无分数不应判 weak: {r}")
    expect(RC.EVIDENCE_MIN_TOP_SCORE == 0.05, "证据阈值应为 0.05（基本无关地板）")


def test_evaluate_step():
    from core.orchestrator.evaluator import (
        evaluate_step, FAILURE, SUCCESS, EVIDENCE_GAP,
    )

    gap = {"status": EVIDENCE_GAP, "reason": "weak"}
    expect(evaluate_step("【会话总结失败】失败】", gap) == FAILURE, "failure 应优先于 gap")
    expect(evaluate_step("【心理咨询回复】正常内容", gap) == EVIDENCE_GAP, "应返回 evidence_gap")
    expect(evaluate_step("【心理咨询回复】正常内容", {"status": SUCCESS}) == SUCCESS, "应返回 success")
    expect(evaluate_step("【心理咨询回复】正常内容", {}) == SUCCESS, "无证据状态应 success")


# ---------------------------------------------------------------- E merge
def test_merge_and_multi():
    from core.orchestrator.remediation import merge_evidence
    from core.helper.RAG_agent import PsychRAGAgent

    primary = [doc("A", "weekly"), doc("B", "daily")]
    extra = [doc("B", "daily"), doc("C", "daily")]
    merged, scores = merge_evidence(primary, {"A": 0.30, "B": 0.50},
                                    extra, {"B": 0.40, "C": 0.25}, final_top_k=3)
    expect([d.doc_id for d in merged] == ["B", "A", "C"], f"合并顺序错误: {[d.doc_id for d in merged]}")
    expect(scores["B"] == 0.5 and len(merged) == 3, f"合并分数/去重错误: {scores}")

    class FakePipeline:
        def retrieve_documents_with_scores(self, query, raw_top_k, final_top_k, **kwargs):
            if "情绪" in query:
                return [doc("A", "weekly"), doc("B", "daily")], {"A": 0.5, "B": 0.4}
            return [doc("B", "daily"), doc("C", "daily")], {"B": 0.6, "C": 0.3}

    agent = object.__new__(PsychRAGAgent)
    agent.pipeline = FakePipeline()
    res = agent.retrieve_multi(["接住情绪", "停止内耗"], final_top_k=3)
    expect(res["queries"] == ["接住情绪", "停止内耗"], f"queries 错误: {res['queries']}")
    expect(len(res["docs"]) == 3, f"应合并为 3 篇: {[d.doc_id for d in res['docs']]}")
    expect(res["docs"][0].doc_id == "B", f"覆盖两次的 B 应排第一: {[d.doc_id for d in res['docs']]}")

    single = agent.retrieve_multi(["接住情绪"], final_top_k=3)
    expect(len(single["docs"]) == 2 and single["scores"] == {"A": 0.5, "B": 0.4},
           f"单查询应等价 retrieve_scored: {single}")


# ---------------------------------------------------------------- F remediation
def test_remediate_guards():
    from core.orchestrator.remediation import remediate_once

    class FakeRAG:
        def __init__(self):
            self.calls = []

        def retrieve_multi(self, queries, **kwargs):
            self.calls.append(("multi", list(queries), kwargs))
            return {"docs": [doc("X", "weekly")], "scores": {"X": 0.7}}

        def retrieve_scored(self, query, **kwargs):
            self.calls.append(("single", query, kwargs))
            return {"docs": [doc("Y", "daily")], "scores": {"Y": 0.6}}

    rag = FakeRAG()
    state = SimpleNamespace(retrieve_budget_left=0, remediation_count=0)
    r = remediate_once(rag, "我该怎么练习", "weak", state)
    expect(r["action"] == "budget_exhausted" and not rag.calls, f"预算为 0 不应检索: {r}")

    state = SimpleNamespace(retrieve_budget_left=1, remediation_count=1)
    r = remediate_once(rag, "我该怎么练习", "weak", state)
    expect(r["action"] == "limit_reached" and not rag.calls, f"已补过不应再检索: {r}")

    import core.tools.primitives as primitives
    original = primitives.decompose_query
    primitives.decompose_query = lambda q, **kw: [q, "子查询一", "子查询二"]
    try:
        state = SimpleNamespace(retrieve_budget_left=1, remediation_count=0)
        r = remediate_once(rag, "我该怎么练习", "weak", state)
        expect(r["action"] == "decompose" and len(r["queries"]) == 3, f"补救动作错误: {r}")
        expect(state.retrieve_budget_left == 0 and state.remediation_count == 1,
               f"预算应扣减 1 且计数 +1: {state}")
        expect(rag.calls and rag.calls[0][0] == "multi", f"应走多查询检索: {rag.calls}")
        expect(rag.calls[0][2]["raw_top_k"] == 25 and rag.calls[0][2]["rerank_pool"] == 20,
               f"补救应扩大候选池: {rag.calls[0][2]}")
        # 第二次调用必须被上限拦住
        r2 = remediate_once(rag, "我该怎么练习", "weak", state)
        expect(r2["action"] == "limit_reached" and len(rag.calls) == 1, f"不得循环补救: {r2}")
    finally:
        primitives.decompose_query = original


# ---------------------------------------------------------------- G 真实链路
def test_real_pipeline():
    try:
        from core.helper.retrieval_pipeline import (
            RetrievalPipeline, get_retrieval_components,
        )
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"检索依赖不可用: {exc}")

    class StubOptimizer:
        def optimize_prompt(self, query, want_hyde=False):
            return {"search_query": query, "match_topics": [], "keywords": [],
                    "distinctive_terms": [], "hyde_experience": "", "hyde_principle": ""}

    query = "下次再遇到类似情况，我具体该怎么练习，先接住对方的情绪、再一起谈问题"
    comps = dict(get_retrieval_components())
    comps["prompt_optimizer"] = StubOptimizer()
    pipe = RetrievalPipeline(**comps)

    ref = pipe.run(query)["final"]["doc_ids"]
    docs, scores = pipe.retrieve_documents_with_scores(query)
    expect([d.doc_id for d in docs] == list(ref), "带分数入口的 doc 顺序必须与 run().final 一致")
    expect(scores and max(scores.values()) > 0, f"score_map 不应为空: {scores}")

    docs2 = pipe.retrieve_documents(query)
    expect([d.doc_id for d in docs2] == list(ref), "retrieve_documents 委托后顺序必须不变")


def main():
    check("A 导入顺序无环", test_import_orders)
    check("B decompose_query", test_decompose)
    check("C evaluate_evidence", test_evaluate_evidence)
    check("D evaluate_step", test_evaluate_step)
    check("E merge / retrieve_multi", test_merge_and_multi)
    check("F remediate_once 硬预算", test_remediate_guards)
    check("G 真实 pipeline 分数契约", test_real_pipeline)

    failed = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 60)
    print(f"总计 {len(RESULTS)} 项，PASS {len(RESULTS) - len(failed)}，FAIL {len(failed)}")
    for name, ok, msg in failed:
        print(f"  - {name}: {msg}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
