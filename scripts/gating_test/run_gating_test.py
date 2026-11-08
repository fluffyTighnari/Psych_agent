# -*- coding: utf-8 -*-
"""4-B 按需检索门控：真实 LLM + 真实检索端到端验证。

直接调 agent_service_entry（不经 HTTP，等价于线上 direct 链路），用两路权威信号判定：
  - 捕获 AgentExecutor verbose 的 `Invoking: <tool>` 行 = 真实工具调用序列（含无 trace 的筛选原语）；
  - 每轮注入一个大容量本地 TraceTracker（避免 500 条环形截断），取外层分类与检索/证据。

在项目根目录运行：
    python scripts/gating_test/run_gating_test.py
结果写入 scripts/gating_test/gating_result.json。
"""
import os
import sys
import io
import re
import json
import time
import contextlib

sys.path.insert(0, os.getcwd())

from core.agent import agent_service_entry
from core.meta_db.context_meta import SESSION_STATE
from core.helper.trace_tracker import GLOBAL_TRACKER, TraceTracker, use_tracker, use_tracker_reset

# gate:
#   retrieve = 期望外层 COUNSELING + 内层先知识检索再咨询
#   direct   = 期望外层 COUNSELING + 内层直接咨询（0 知识检索）
#   filter   = 期望外层 TOOL + 内层调用筛选工具（不经咨询）
TURNS = [
    ("retrieve",
     "我发现自己很容易在人际交往后反复回放和自责。上次聊天时我为了显得务实，直接跳过了对方情绪化的表达，只谈怎么解决问题，当时觉得高效，事后却一直想我是不是太冷漠了。这种当时理性、事后内疚的模式，我该怎么理解？"),
    ("direct",
     "嗯，你说得对，我当时其实心里挺慌的，又有点委屈，只是没表现出来。"),
    ("retrieve",
     "那下次再遇到类似情况，我具体该怎么练习，先接住对方的情绪、再一起谈问题？"),
    ("filter",
     "帮我找所有关于自我否定的日记。"),
    ("direct",
     "谢谢你，我现在感觉清楚多了。"),
]

FILTER_TOOLS = ("meta_filter_tool", "precise_text_filter_tool",
                "search_memory_tool", "precise_memory_filter_tool")


def analyze(local, invoking, reply):
    classify = None
    retrieve_done = 0
    retrieve_docs = None
    retrieve_evidence = None
    consult_trace = None
    errors = []
    for t in local.get_all_trace():
        stage = t.get("stage", "")
        label = t.get("label", "")
        content = t.get("content") or {}
        if stage == "classify_intent" and "完成" in label:
            classify = content.get("result")
        if label == "retrieve_knowledge_tool 完成":
            retrieve_done += 1
            retrieve_docs = (content.get("principle_count"), content.get("experience_count"))
            retrieve_evidence = {k: content.get(k) for k in
                                 ("query", "evidence_status", "evidence_reason", "top_score", "remediation_action")}
        if label == "调用工具: psychological_consult_tool":
            consult_trace = {"retrieved_knowledge": content.get("retrieved_knowledge"),
                             "has_chat_history": content.get("has_chat_history")}
        if t.get("is_error"):
            errors.append({"stage": stage, "label": label, "msg": (t.get("error_msg") or "")[:160]})

    did_retrieve = "retrieve_knowledge_tool" in invoking
    did_consult = "psychological_consult_tool" in invoking
    did_filter = any(x in invoking for x in FILTER_TOOLS)
    # return_direct 生效后，最终回复应就是工具原文（以哨兵开头）
    sentinels = ("【心理咨询回复】", "【模糊筛选匹配结果】", "【精准文本匹配结果】",
                 "【记忆搜索结果】", "【精准记忆筛选结果】", "【会话总结完成】")
    reply_sentinel = next((s for s in sentinels if (reply or "").startswith(s)), None)
    # 最终回复是否自身重复（开头句出现次数）
    head = (reply or "")[:18]
    dup = reply.count(head) if head else 0
    return {
        "classify": classify,
        "invoking": invoking,
        "did_retrieve": did_retrieve,
        "did_consult": did_consult,
        "did_filter": did_filter,
        "retrieve_docs": retrieve_docs,
        "retrieve_evidence": retrieve_evidence,
        "consult_trace": consult_trace,
        "reply_sentinel": reply_sentinel,
        "reply_len": len(reply or ""),
        "reply_head_dup": dup,
        "errors": errors,
    }


def judge(gate, a):
    if gate == "retrieve":
        ok = a["classify"] == "COUNSELING" and a["did_retrieve"] and a["did_consult"]
        return ok, f"外层COUNSELING(实际{a['classify']})；retrieve→consult(实际 retrieve={a['did_retrieve']}, consult={a['did_consult']})"
    if gate == "direct":
        ok = a["classify"] == "COUNSELING" and a["did_consult"] and not a["did_retrieve"]
        return ok, f"外层COUNSELING(实际{a['classify']})；直接consult 0检索(实际 retrieve={a['did_retrieve']})"
    ok = a["classify"] == "TOOL" and a["did_filter"] and not a["did_consult"]
    return ok, f"外层TOOL(实际{a['classify']})；筛选工具(实际 {a['invoking']})"


def main():
    SESSION_STATE.clear_all()
    results = []
    print("=" * 70)
    print("4-B 按需检索门控 · 真实端到端测试（清空会话，锁定 direct 模式）")
    print("=" * 70, flush=True)

    for i, (gate, text) in enumerate(TURNS, 1):
        GLOBAL_TRACKER.clear_trace()
        local = TraceTracker(False)
        local.MAX_TRACE = 100000
        token = use_tracker(local)
        buf = io.StringIO()
        t0 = time.time()
        try:
            with contextlib.redirect_stdout(buf):
                res = agent_service_entry(text, situation=None, mode="direct")
        finally:
            use_tracker_reset(token)
        dt = time.time() - t0
        log = buf.getvalue()
        invoking = re.findall(r"Invoking: `([a-z_]+)`", log)
        reply = res.get("reply", "") or ""
        a = analyze(local, invoking, reply)
        ok, note = judge(gate, a)
        rec = {
            "turn": i, "expected_gate": gate, "input": text,
            "classify": a["classify"], "tool_sequence": a["invoking"],
            "did_retrieve": a["did_retrieve"], "did_consult": a["did_consult"],
            "did_filter": a["did_filter"], "retrieve_docs_principle_exp": a["retrieve_docs"],
            "retrieve_evidence": a["retrieve_evidence"],
            "consult_trace": a["consult_trace"],
            "reply_sentinel": a["reply_sentinel"],
            "intent_type": res.get("intent_type"),
            "reply_len": a["reply_len"], "reply_head_dup": a["reply_head_dup"],
            "reply_head": reply[:200], "elapsed_sec": round(dt, 1),
            "gate_correct": ok, "judge_note": note, "errors": a["errors"],
        }
        results.append(rec)
        print(f"[轮{i}] 期望={gate:8s} 分类={a['classify']} 工具序列={a['invoking']}")
        print(f"       命中(原则,经历)={a['retrieve_docs']} 证据={a['retrieve_evidence']} consult证据={a['consult_trace']} 哨兵={a['reply_sentinel']} "
              f"intent={res.get('intent_type')} 回复长度={a['reply_len']} 耗时={dt:.1f}s 门控={'通过' if ok else '不符'}")
        print(f"       {note}")
        if a["errors"]:
            print(f"       !! 异常: {a['errors']}")
        print(flush=True)

    SESSION_STATE.clear_all()
    out_dir = os.path.join("scripts", "gating_test")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "gating_result.json")
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    n_ok = sum(1 for r in results if r["gate_correct"])
    print("=" * 70)
    print(f"门控正确 {n_ok}/{len(results)}；结果已保存 {out}")
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
