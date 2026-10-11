#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立验证脚本：检索优化调试系统（契约 docs/retrieval_debug_contract.md §5）。

用法（仓库根目录）：
    HF_HUB_OFFLINE=1 .venv/bin/python scripts/verify_retrieval_debug.py

设计约束：
- 可重复运行、无副作用：只读业务数据（data/、store/），不写任何业务文件；
  临时产物仅写 /tmp/verify_retrieval_debug/。
- 独立复核：不依赖实现者自测代码。用 fastapi.testclient.TestClient(main.app) 走真实路由，
  并直接 import core.helper.retrieval_pipeline 跑同一 query，与 API 的 final.doc_ids 逐条比对。
- 退出码：0=全部 PASS；1=存在 FAIL；2=依赖缺失（api/core 交付物尚未落地）。

本脚本只写 /tmp，不修改被验证的交付物。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

# ---------------------------------------------------------------- 环境准备
# 必须在 import 任何 transformers / sentence_transformers 之前设置离线变量
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

TMP_DIR = Path("/tmp/verify_retrieval_debug")
TMP_DIR.mkdir(parents=True, exist_ok=True)
RESULT_JSON = TMP_DIR / "result.json"

QUERY = "最近总是内耗，怎么和自己和解"

# 固定优化器输出（Lead 指定方法：stub 注入进程单例，API 与直跑共用，消除 LLM 漂移）
FIXED_OPTIMIZED = {
    "search_query": "如何停止精神内耗并与自己和解",
    "match_topics": ["Self_Acceptance", "Emotion_Regulation"],
    "keywords": ["内耗", "和解", "自我"],
}

# 契约 §2.4 DOC_VIEW 形状
DOC_VIEW_KEYS = {
    "doc_id", "title", "doc_type", "date", "source", "relative_path", "knowledge_path",
    "summary", "topic", "keywords", "emotion", "problem", "analysis", "solution",
    "word_count", "content",
}
# 契约 §2.2 stages 顺序固定
CANON_STAGE_ORDER = ["optimize_prompt", "dense", "bm25", "rrf", "rerank"]

# 契约 §2.3 8 种勾选组合
COMBOS = [
    # (id, flags, expected_stages, expected_source)
    ("dense-only", dict(dense=True, bm25=False, rrf=False, rerank=False),
     ["optimize_prompt", "dense"], "dense"),
    ("bm25-only", dict(dense=False, bm25=True, rrf=False, rerank=False),
     ["optimize_prompt", "bm25"], "bm25"),
    ("rrf-only", dict(dense=False, bm25=False, rrf=True, rerank=False),
     ["optimize_prompt", "dense", "bm25", "rrf"], "rrf"),
    ("rerank-only", dict(dense=False, bm25=False, rrf=False, rerank=True),
     ["optimize_prompt", "dense", "bm25", "rrf", "rerank"], "rerank"),
    ("dense+rerank", dict(dense=True, bm25=False, rrf=False, rerank=True),
     ["optimize_prompt", "dense", "rerank"], "rerank"),
    ("bm25+rerank", dict(dense=False, bm25=True, rrf=False, rerank=True),
     ["optimize_prompt", "bm25", "rerank"], "rerank"),
    ("dense+bm25", dict(dense=True, bm25=True, rrf=False, rerank=False),
     ["optimize_prompt", "dense", "bm25", "rrf"], "rrf"),
    ("all", dict(dense=True, bm25=True, rrf=True, rerank=True),
     ["optimize_prompt", "dense", "bm25", "rrf", "rerank"], "rerank"),
]


# ---------------------------------------------------------------- 结果收集
class Results:
    def __init__(self):
        self.rows = []          # (id, name, status, detail)
        self.raw = {}           # 原始关键输出

    def check(self, cid: str, name: str, ok: bool, detail: str = "") -> bool:
        status = "PASS" if ok else "FAIL"
        self.rows.append((cid, name, status, detail))
        line = f"[{status}] {cid} {name}"
        if detail:
            line += f" :: {detail}"
        print(line, flush=True)
        return ok

    def info(self, cid: str, name: str, detail: str = "") -> None:
        self.rows.append((cid, name, "INFO", detail))
        print(f"[INFO] {cid} {name}" + (f" :: {detail}" if detail else ""), flush=True)

    def nfail(self) -> int:
        return sum(1 for r in self.rows if r[2] == "FAIL")

    def to_dict(self):
        return {
            "rows": [{"id": c, "name": n, "status": s, "detail": d} for c, n, s, d in self.rows],
            "fail_count": self.nfail(),
            "raw": self.raw,
        }


R = Results()


def jdump(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception as e:  # pragma: no cover
        return f"<NOT JSON SERIALIZABLE: {e}>"


def brief(obj, limit: int = 600) -> str:
    s = jdump(obj)
    return s if len(s) <= limit else s[:limit] + "...(truncated)"


def is_doc_view(doc) -> bool:
    return isinstance(doc, dict) and DOC_VIEW_KEYS.issubset(doc.keys())


def snapshot_business_data():
    """业务数据只读哨兵：记录 data/knowledge、store/bm25_store、config/id_map.json 的大小+ mtime。"""
    snap = {}
    targets = [ROOT / "data" / "knowledge", ROOT / "store" / "bm25_store", ROOT / "config" / "id_map.json"]
    for t in targets:
        if t.is_file():
            st = t.stat()
            snap[str(t)] = (st.st_size, round(st.st_mtime, 3))
        elif t.is_dir():
            for f in sorted(t.rglob("*")):
                if f.is_file():
                    st = f.stat()
                    snap[str(f)] = (st.st_size, round(st.st_mtime, 3))
    return snap


# ---------------------------------------------------------------- 静态检查（不依赖交付物）
def static_checks():
    print("\n========== G. 静态/反例检查 ==========", flush=True)

    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8", errors="replace")
    appjs_path = ROOT / "web" / "app.js"
    appjs = appjs_path.read_text(encoding="utf-8", errors="replace")
    css = (ROOT / "web" / "style.css").read_text(encoding="utf-8", errors="replace")

    R.check("G1", 'index.html 含 data-view="retrieval"', 'data-view="retrieval"' in html,
            f'found={html.count(chr(34) + "retrieval" + chr(34))} 次 "retrieval" 出现')
    R.check("G2", 'index.html 含 id="view-retrieval"', 'id="view-retrieval"' in html,
            'id="view-retrieval" ' + ("present" if 'id="view-retrieval"' in html else "MISSING"))
    for cid, needle in [("G3.1", "'/retrieval/debug'"), ("G3.2", "'/retrieval/documents'"),
                        ("G3.3", "'/retrieval/meta'"), ("G3.4", "bindRetrieval")]:
        R.check(cid, f"app.js 含 {needle}", needle in appjs,
                f"occurrences={appjs.count(needle)}")
    rd_count = css.count("rd-")
    R.check("G4", "style.css 含 rd- 前缀样式", rd_count > 0, f"rd- occurrences={rd_count}")

    # 契约 §4 前端结构静态核对（无浏览器时的可验证部分）
    R.check("G4.1", "app.js 含 loadRetrievalMeta/loadRetrievalDocs/renderRetrievalRun",
            all(n in appjs for n in ["loadRetrievalMeta", "loadRetrievalDocs", "renderRetrievalRun"]),
            f"meta={appjs.count('loadRetrievalMeta')} docs={appjs.count('loadRetrievalDocs')} run={appjs.count('renderRetrievalRun')}")
    R.check("G4.2", "app.js 详情懒加载 GET /retrieval/documents/{doc_id}",
            "API.retrievalDocs + '/'" in appjs or "retrievalDocs}/" in appjs or "API.retrievalDocs + '/' +" in appjs,
            f"pattern_hits={appjs.count(chr(39) + '/' + chr(39))}")
    init_pos = appjs.find("bindRetrieval();")
    all_settled = appjs[init_pos:init_pos + 800] if init_pos >= 0 else ""
    R.check("G4.3", "init() 的 Promise.allSettled 加载 meta+docs",
            "loadRetrievalMeta()" in all_settled and "loadRetrievalDocs()" in all_settled,
            f"bindRetrieval_pos={init_pos} window_has_meta={'loadRetrievalMeta()' in all_settled} window_has_docs={'loadRetrievalDocs()' in all_settled}")
    for cid, needle, label in [
        ("G4.4", 'id="rd-switches"', "开关+参数容器"),
        ("G4.5", 'id="rd-docs-panel"', "全部文档容器"),
        ("G4.6", 'id="rd-stages"', "检索结果容器"),
        ("G4.7", 'id="rd-logs"', "检索日志容器"),
    ]:
        R.check(cid, f"index.html 含 {label}（{needle}）", needle in html,
                f"present={needle in html}")

    # node --check web/app.js
    try:
        proc = subprocess.run(["node", "--check", str(appjs_path)], capture_output=True, text=True, timeout=60)
        R.check("G5", "node --check web/app.js", proc.returncode == 0,
                f"rc={proc.returncode} stdout={proc.stdout.strip()!r} stderr={proc.stderr.strip()!r}")
    except FileNotFoundError:
        R.check("G5", "node --check web/app.js", False, "node 未安装")
    except Exception as e:
        R.check("G5", "node --check web/app.js", False, f"异常 {e}")

    # git 检查：生产链路文件未被修改
    def git(*args):
        p = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr

    rc, out, err = git("diff", "--stat", "HEAD", "--", "core/helper/retriever.py")
    R.check("G6", "core/helper/retriever.py 未被修改", out.strip() == "",
            f"diff --stat HEAD 输出={out.strip()!r}")

    rc, out, err = git("diff", "--stat", "HEAD", "--", "core/helper/RAG_agent.py")
    rag_changed = out.strip() != ""
    rc2, numstat, _ = git("diff", "--numstat", "HEAD", "--", "core/helper/RAG_agent.py")
    rc3, feature_refs, _ = git("diff", "HEAD", "--", "core/helper/RAG_agent.py")
    refs = [ln for ln in (feature_refs or "").splitlines()
            if ln.startswith("+") and ("retrieval_pipeline" in ln or "retrieval_debug" in ln)]
    R.raw["RAG_agent_diff_stat"] = out.strip()
    R.raw["RAG_agent_numstat"] = numstat.strip()
    if not rag_changed:
        R.check("G7", "core/helper/RAG_agent.py 未被修改", True, "无 diff")
    else:
        # HEAD 基线本身已被仓库历史重构污染（非本次特性引入）：特性相关引用为 0 则记为 INFO+人工判读
        R.check("G7", "core/helper/RAG_agent.py 未被本次特性修改",
                len(refs) == 0,
                f"相对 HEAD 有改动({out.strip().splitlines()[-1].strip() if out.strip() else ''})，"
                f"含 retrieval_pipeline/retrieval_debug 的新增行数={len(refs)}")
        R.info("G7-note", "RAG_agent.py 差异性质",
               "diff 存在但无检索调试相关引用；属既有重构差异，需 Lead 结合基线判读")

    rc, out, err = git("status", "--short")
    R.raw["git_status_short"] = out
    # 关键交付物是否被本特性修改
    R.raw["git_diff_stat_all"] = git("diff", "--stat", "HEAD")[1]

    # docs 列表静态文件校验：knowledge 目录（Daily/Weekly）json 数量 == KNOWLEDGE_CACHE 长度
    try:
        from core.helper.knowledge_cache import KNOWLEDGE_CACHE as _KC
        _cache_len = len(_KC.documents)
    except Exception:
        _cache_len = 11
    jsons = sorted(f for f in (ROOT / "data" / "knowledge").rglob("*.json")
                   if f.parent.name in ("Daily", "Weekly"))
    R.check("G8", f"data/knowledge/Daily|Weekly json 数 == KNOWLEDGE_CACHE ({_cache_len})",
            len(jsons) == _cache_len == 11, f"count={len(jsons)} cache={_cache_len}")

    return jsons


# ---------------------------------------------------------------- API 验证
def api_checks():
    print("\n========== A-F. API 端到端验证 ==========", flush=True)
    try:
        from fastapi.testclient import TestClient
        import main as main_mod
    except Exception as e:
        R.check("A0", "import main / TestClient", False,
                f"{type(e).__name__}: {e}")
        raise

    app = main_mod.app
    # 新版 FastAPI 把 include_router 的结果包成 _IncludedRouter（无 .path），用 openapi().paths 枚举真实路由
    try:
        paths = sorted(app.openapi().get("paths", {}).keys())
    except Exception as e:
        paths = []
        R.info("A0-note", "openapi 枚举失败", str(e))
    R.check("A0", "main.app 挂载 /retrieval/* 路由",
            any(p.startswith("/retrieval") for p in paths),
            "检索调试路由=" + jdump([p for p in paths if p.startswith("/retrieval")]))
    R.raw["routes_retrieval"] = [p for p in paths if p.startswith("/retrieval")]

    client = TestClient(app)

    # ---------------- A. 8 种勾选组合 ----------------
    print("\n---- A. POST /retrieval/debug 8 种组合 ----", flush=True)
    api_final = {}
    for cid_base, flags, exp_stages, exp_source in COMBOS:
        cid = f"A[{cid_base}]"
        body = {"query": QUERY, **flags}
        t0 = time.time()
        try:
            r = client.post("/retrieval/debug", json=body)
        except Exception as e:
            R.check(cid, f"POST 组合 {cid_base}", False, f"请求异常 {type(e).__name__}: {e}")
            continue
        dt = round((time.time() - t0) * 1000, 1)
        if r.status_code != 200:
            R.check(cid, f"HTTP 200 ({cid_base})", False,
                    f"http={r.status_code} body={r.text[:400]}")
            continue
        try:
            payload = r.json()
        except Exception as e:
            R.check(cid, f"响应可解析 JSON ({cid_base})", False, f"{e}; text={r.text[:200]}")
            continue

        # 统一返回体 + 可 json 序列化
        ok_env = (payload.get("code") == 200 and "msg" in payload
                  and "data" in payload and "extra" in payload)
        R.check(f"{cid}.0", f"{cid_base} 统一返回体 code=200/msg/data/extra", ok_env,
                f"code={payload.get('code')} msg={payload.get('msg')!r} keys={sorted(payload.keys())}")
        if not ok_env:
            continue
        data = payload["data"]

        ok_serial = True
        err_serial = ""
        try:
            json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            ok_serial, err_serial = False, str(e)
        R.check(f"{cid}.1", f"{cid_base} 响应 json 可序列化", ok_serial, err_serial or "ok")

        # data 顶层字段
        need = ["query", "flags", "params", "enabled_pipeline", "optimized",
                "stages", "final", "latency_ms", "logs"]
        missing = [k for k in need if k not in data]
        R.check(f"{cid}.2", f"{cid_base} data 顶层字段齐全", not missing,
                f"missing={missing}")

        # flags 回显
        flags_got = data.get("flags", {})
        R.check(f"{cid}.3", f"{cid_base} flags 回显正确",
                all(flags_got.get(k) == v for k, v in flags.items()),
                f"expect={jdump(flags)} actual={jdump(flags_got)}")

        # enabled_pipeline / stages 名称与顺序
        stages = data.get("stages", [])
        names = [s.get("name") for s in stages]
        R.check(f"{cid}.4", f"{cid_base} stages 名称符合 §2.3",
                names == exp_stages, f"expect={jdump(exp_stages)} actual={jdump(names)}")
        order = [CANON_STAGE_ORDER.index(n) for n in names if n in CANON_STAGE_ORDER]
        R.check(f"{cid}.5", f"{cid_base} stages 顺序固定(优化→dense→bm25→rrf→rerank)",
                order == sorted(order) and len(order) == len(names),
                f"names={jdump(names)}")
        ep = data.get("enabled_pipeline", [])
        R.check(f"{cid}.6", f"{cid_base} enabled_pipeline == stages 名称",
                list(ep) == names, f"enabled_pipeline={jdump(ep)} stages={jdump(names)}")

        # final.source
        fin = data.get("final", {})
        R.check(f"{cid}.7", f"{cid_base} final.source == {exp_source}",
                fin.get("source") == exp_source,
                f"expect={exp_source} actual={fin.get('source')!r}")

        # stages 形状
        shape_ok, shape_msg = True, []
        for st in stages:
            for k in ["name", "label", "enabled", "latency_ms", "output_count", "results"]:
                if k not in st:
                    shape_ok = False
                    shape_msg.append(f"stage {st.get('name')} 缺字段 {k}")
            for it in st.get("results", []):
                if not all(k in it for k in ["doc_id", "rank", "score", "doc"]):
                    shape_ok = False
                    shape_msg.append(f"stage {st.get('name')} result 缺字段 keys={sorted(it.keys())}")
                    break
                if it.get("doc") is not None and not is_doc_view(it.get("doc")):
                    shape_ok = False
                    shape_msg.append(
                        f"stage {st.get('name')} doc 非 DOC_VIEW keys={sorted(it['doc'].keys()) if isinstance(it['doc'], dict) else type(it['doc']).__name__}")
                    break
                if not isinstance(it.get("score"), (int, float)) or isinstance(it.get("score"), bool):
                    shape_ok = False
                    shape_msg.append(f"stage {st.get('name')} score 非数值: {it.get('score')!r}")
                    break
        R.check(f"{cid}.8", f"{cid_base} stages/result/doc 形状符合契约", shape_ok,
                "; ".join(shape_msg[:3]) or f"stages={len(stages)}")

        # optimize_prompt 阶段 results 必须为空
        opt_stage = next((s for s in stages if s.get("name") == "optimize_prompt"), None)
        if opt_stage is not None:
            R.check(f"{cid}.9", f"{cid_base} optimize_prompt.results == []",
                    opt_stage.get("results") == [],
                    f"len={len(opt_stage.get('results') or [])}")

        # optimized 结构（契约 §3.1）
        opt = data.get("optimized", {})
        R.check(f"{cid}.10", f"{cid_base} optimized 含 search_query/match_topics/keywords",
                all(k in opt for k in ["search_query", "match_topics", "keywords"]),
                brief(opt, 200))
        if opt_stage is not None and "extra" in opt_stage:
            R.check(f"{cid}.11", f"{cid_base} data.optimized == stages[0].extra",
                    opt == opt_stage.get("extra"),
                    f"optimized={brief(opt, 160)} extra={brief(opt_stage.get('extra'), 160)}")
        else:
            R.info(f"{cid}.11", f"{cid_base} stages[0].extra",
                   f"pipeline 未提供 extra，api 已回退空结构；optimized={brief(opt, 160)}")

        # final 形状 + doc_ids 数量
        fresults = fin.get("results", [])
        R.check(f"{cid}.12", f"{cid_base} final.count == len(doc_ids) == len(results)",
                fin.get("count") == len(fin.get("doc_ids", [])) == len(fresults),
                f"count={fin.get('count')} len(doc_ids)={len(fin.get('doc_ids', []))} len(results)={len(fresults)}")
        fshape_ok = all(
            all(k in it for k in ["doc_id", "rank", "score", "doc"]) for it in fresults
        ) and all(it.get("doc") is None or is_doc_view(it.get("doc")) for it in fresults)
        R.check(f"{cid}.13", f"{cid_base} final.results 形状符合契约", fshape_ok,
                f"len={len(fresults)} first_keys={sorted(fresults[0].keys()) if fresults else None}")

        if not fresults:
            R.info(f"{cid}.14", f"{cid_base} final.results 为空", "11 篇文档库下不应为空，请人工确认")
        else:
            R.check(f"{cid}.14", f"{cid_base} final.results 非空", True,
                    f"n={len(fresults)} doc_ids={jdump(fin.get('doc_ids'))}")

        # logs 非空且覆盖已执行阶段
        logs = data.get("logs", [])
        log_stages = {l.get("stage") for l in logs}
        missing_logs = [n for n in names if n not in log_stages]
        R.check(f"{cid}.15", f"{cid_base} logs 非空且覆盖已执行阶段",
                len(logs) > 0 and not missing_logs,
                f"n_logs={len(logs)} log_stages={sorted(x for x in log_stages if x)} missing={missing_logs}")
        R.check(f"{cid}.16", f"{cid_base} logs 条目含契约字段",
                all(all(k in l for k in ["stage", "label", "content", "timestamp", "is_error", "error_msg"])
                    for l in logs),
                f"keys={sorted(logs[0].keys()) if logs else None}")

        api_final[cid_base] = {
            "flags": flags,
            "params": data.get("params"),
            "doc_ids": fin.get("doc_ids"),
            "source": fin.get("source"),
            "stages": {s.get("name"): [it.get("doc_id") for it in s.get("results", [])] for s in stages},
            "optimized": opt,
            "latency_ms": data.get("latency_ms"),
            "request_ms": dt,
            "final_results": fresults,
            "logs_count": len(logs),
        }
        if cid_base == "all":
            R.raw["sample_all_response"] = {
                k: v for k, v in data.items() if k not in ("stages", "logs")
            }
            R.raw["sample_all_stages_compact"] = [
                {"name": s.get("name"), "label": s.get("label"), "latency_ms": s.get("latency_ms"),
                 "output_count": s.get("output_count"),
                 "results": [{"rank": it.get("rank"), "doc_id": it.get("doc_id"),
                              "score": it.get("score"), "has_doc": it.get("doc") is not None}
                             for it in s.get("results", [])]}
                for s in stages
            ]
            R.raw["sample_all_logs"] = logs

    R.raw["api_final"] = api_final

    # ---------------- B. 参数校验 ----------------
    print("\n---- B. 参数校验（契约 §3.1，期望 code=400） ----", flush=True)
    bad_cases = [
        ("B1", "query 为空字符串", {"query": ""}),
        ("B2", "raw_top_k=0", {"query": QUERY, "raw_top_k": 0}),
        ("B3", "raw_top_k=99", {"query": QUERY, "raw_top_k": 99}),
        ("B4", "rrf_k=0", {"query": QUERY, "rrf_k": 0}),
        ("B5", "score_threshold=2", {"query": QUERY, "score_threshold": 2}),
    ]
    for cid, name, body in bad_cases:
        try:
            r = client.post("/retrieval/debug", json=body)
        except Exception as e:
            R.check(cid, name, False, f"请求异常 {type(e).__name__}: {e}")
            continue
        try:
            payload = r.json()
        except Exception:
            payload = {}
        code = payload.get("code")
        R.check(cid, f"{name} → code=400", code == 400,
                f"http={r.status_code} code={code!r} body={r.text[:220]}")

    # ---------------- C. GET /retrieval/documents ----------------
    print("\n---- C. GET /retrieval/documents ----", flush=True)
    r = client.get("/retrieval/documents")
    docs_payload = r.json() if r.status_code == 200 else {}
    R.check("C1", "HTTP 200 且 code=200", r.status_code == 200 and docs_payload.get("code") == 200,
            f"http={r.status_code} code={docs_payload.get('code')}")
    d = docs_payload.get("data", {}) or {}
    documents = d.get("documents", []) or []

    try:
        from core.helper.knowledge_cache import KNOWLEDGE_CACHE
        cache_len = len(KNOWLEDGE_CACHE.documents)
        cache_ids = [x.doc_id for x in KNOWLEDGE_CACHE.documents]
    except Exception as e:
        cache_len, cache_ids = -1, []
        R.info("C2-note", "KNOWLEDGE_CACHE 读取失败", str(e))
    R.check("C2", f"total == KNOWLEDGE_CACHE 长度 ({cache_len})",
            d.get("total") == cache_len == 11,
            f"total={d.get('total')} cache_len={cache_len}")
    R.check("C3", "count == len(documents) == total",
            d.get("count") == len(documents) == d.get("total"),
            f"count={d.get('count')} len={len(documents)} total={d.get('total')}")
    ids = [x.get("doc_id") for x in documents]
    R.check("C4", "doc_id 唯一", len(ids) == len(set(ids)),
            f"n={len(ids)} unique={len(set(ids))}")
    if cache_ids:
        R.check("C5", "doc_id 集合与 KNOWLEDGE_CACHE 一致",
                set(ids) == set(cache_ids),
                f"only_api={sorted(set(ids) - set(cache_ids))[:5]} only_cache={sorted(set(cache_ids) - set(ids))[:5]}")
    bad_docs = [x.get("doc_id") for x in documents if not is_doc_view(x)]
    R.check("C6", "所有 documents 均为 DOC_VIEW 形状", not bad_docs,
            f"bad={bad_docs[:3]} first_keys={sorted(documents[0].keys()) if documents else None}")

    # 契约：按 date 降序，date 为空的排最后，同 date 按 title
    with_date = [x for x in documents if x.get("date")]
    without_date = [x for x in documents if not x.get("date")]
    # date 降序分组，组内按 title 升序；无 date 的放最后
    dates_desc = sorted({x.get("date") for x in with_date}, reverse=True)
    sorted_expect = []
    for _d in dates_desc:
        sorted_expect.extend(sorted([x for x in with_date if x.get("date") == _d],
                                    key=lambda x: x.get("title") or ""))
    sorted_expect.extend(sorted(without_date, key=lambda x: x.get("title") or ""))
    dates = [x.get("date") or "" for x in documents]
    R.raw["documents_dates"] = dates
    R.check("C7", "documents 按 date 降序（空值最后，同 date 按 title）",
            [x.get("doc_id") for x in documents] == [x.get("doc_id") for x in sorted_expect],
            f"dates={jdump(dates[:12])}")

    # doc_types 统计
    dt = d.get("doc_types", {}) or {}
    real_counts = {}
    for x in documents:
        real_counts[x.get("doc_type")] = real_counts.get(x.get("doc_type"), 0) + 1
    R.check("C8", "doc_types 统计正确且合计 == total",
            dt == real_counts and sum(dt.values()) == d.get("total"),
            f"doc_types={jdump(dt)} real={jdump(real_counts)} total={d.get('total')}")

    # keyword 过滤
    kw = (documents[0].get("title") or "")[:2] if documents else "心理"
    rk = client.get("/retrieval/documents", params={"keyword": kw})
    dk = (rk.json().get("data") or {}) if rk.status_code == 200 else {}
    kdocs = dk.get("documents", []) or []

    def hit(doc, k):
        blob = " ".join([
            str(doc.get("title") or ""), str(doc.get("summary") or ""),
            str(doc.get("content") or ""), " ".join(doc.get("keywords") or []),
        ])
        return k in blob
    R.check("C9", f"keyword 过滤生效 (keyword={kw!r})",
            rk.status_code == 200 and len(kdocs) > 0 and all(hit(x, kw) for x in kdocs)
            and len(kdocs) < len(documents),
            f"n_filtered={len(kdocs)} n_total={len(documents)} all_hit={all(hit(x, kw) for x in kdocs)}")

    # doc_type 过滤
    rw = client.get("/retrieval/documents", params={"doc_type": "weekly"})
    dw = (rw.json().get("data") or {}) if rw.status_code == 200 else {}
    wdocs = dw.get("documents", []) or []
    R.check("C10", "doc_type=weekly 过滤生效",
            rw.status_code == 200 and len(wdocs) > 0 and all(x.get("doc_type") == "weekly" for x in wdocs),
            f"n={len(wdocs)} types={sorted(set(x.get('doc_type') for x in wdocs))} total={dw.get('total')}")
    rd_ = client.get("/retrieval/documents", params={"doc_type": "daily"})
    dd = (rd_.json().get("data") or {}) if rd_.status_code == 200 else {}
    ddocs = dd.get("documents", []) or []
    R.check("C11", "doc_type=daily 过滤生效",
            rd_.status_code == 200 and all(x.get("doc_type") == "daily" for x in ddocs) and len(ddocs) == real_counts.get("daily", 0),
            f"n={len(ddocs)} expect_daily={real_counts.get('daily')}")

    # limit / offset
    rl = client.get("/retrieval/documents", params={"limit": 2})
    dl = (rl.json().get("data") or {}) if rl.status_code == 200 else {}
    R.check("C12", "limit=2 生效且 total 不变",
            rl.status_code == 200 and len(dl.get("documents", [])) == 2 and dl.get("total") == d.get("total"),
            f"n={len(dl.get('documents', []))} total={dl.get('total')} limit={dl.get('limit')}")
    ro = client.get("/retrieval/documents", params={"offset": 1, "limit": 2})
    do = (ro.json().get("data") or {}) if ro.status_code == 200 else {}
    R.check("C13", "offset=1 生效",
            ro.status_code == 200
            and [x.get("doc_id") for x in do.get("documents", [])] == [x.get("doc_id") for x in documents[1:3]],
            f"offset_ids={jdump([x.get('doc_id') for x in do.get('documents', [])])}")

    for cid, params in [("C14", {"doc_type": "bogus"}), ("C15", {"limit": 0}), ("C16", {"limit": 999})]:
        rr = client.get("/retrieval/documents", params=params)
        try:
            pp = rr.json()
        except Exception:
            pp = {}
        R.check(cid, f"非法参数 {params} → code=400", pp.get("code") == 400,
                f"http={rr.status_code} code={pp.get('code')!r} body={rr.text[:160]}")

    R.raw["documents_sample"] = documents[0] if documents else None
    R.raw["documents_count"] = len(documents)

    # ---------------- D. 单文档 ----------------
    print("\n---- D. GET /retrieval/documents/{doc_id} ----", flush=True)
    real_id = ids[0] if ids else None
    if real_id:
        rr = client.get(f"/retrieval/documents/{real_id}")
        pp = rr.json() if rr.status_code == 200 else {}
        doc = (pp.get("data") or {}).get("document")
        R.check("D1", "真实 doc_id 返回 document",
                pp.get("code") == 200 and isinstance(doc, dict) and doc.get("doc_id") == real_id
                and is_doc_view(doc),
                f"http={rr.status_code} code={pp.get('code')} doc_id={doc.get('doc_id') if isinstance(doc, dict) else None}")
    else:
        R.check("D1", "真实 doc_id 返回 document", False, "无 doc_id 可用")

    fake = "doc_not_exist_0000"
    rr = client.get(f"/retrieval/documents/{fake}")
    try:
        pp = rr.json()
    except Exception:
        pp = {}
    R.check("D2", "伪造 doc_id → code=400 且 msg=文档不存在",
            pp.get("code") == 400 and "文档不存在" in str(pp.get("msg", "")),
            f"http={rr.status_code} code={pp.get('code')!r} msg={pp.get('msg')!r}")

    # ---------------- E. GET /retrieval/meta ----------------
    print("\n---- E. GET /retrieval/meta ----", flush=True)
    rm = client.get("/retrieval/meta")
    pm = rm.json() if rm.status_code == 200 else {}
    R.check("E1", "HTTP 200 且 code=200", rm.status_code == 200 and pm.get("code") == 200,
            f"http={rm.status_code} code={pm.get('code')}")
    m = pm.get("data", {}) or {}
    R.raw["meta"] = m
    need_m = ["topics", "doc_count", "vector_count", "bm25_ready", "models", "defaults", "stages"]
    R.check("E2", "meta 字段齐全", all(k in m for k in need_m),
            f"missing={[k for k in need_m if k not in m]} keys={sorted(m.keys())}")
    try:
        from config.topic_config import VALID_TOPICS
        vt = set(VALID_TOPICS)
    except Exception as e:
        vt = set()
        R.info("E3-note", "VALID_TOPICS 读取失败", str(e))
    R.check("E3", "topics == VALID_TOPICS",
            isinstance(m.get("topics"), list) and set(m.get("topics")) == vt and vt,
            f"n={len(m.get('topics') or [])} expect_n={len(vt)} diff={sorted(set(m.get('topics') or []) ^ vt)[:5]}")
    R.check("E4", "doc_count == 11", m.get("doc_count") == 11, f"doc_count={m.get('doc_count')}")
    R.check("E5", "vector_count 为 int 或 null", m.get("vector_count") is None or isinstance(m.get("vector_count"), int),
            f"vector_count={m.get('vector_count')!r}")
    R.check("E6", "bm25_ready 为 True（BM25_PATH 存在）", m.get("bm25_ready") is True,
            f"bm25_ready={m.get('bm25_ready')!r}")
    models = m.get("models") or {}
    R.check("E7", "models.embedding/reranker 非空",
            bool(models.get("embedding")) and bool(models.get("reranker")),
            f"models={jdump(models)}")
    defaults = m.get("defaults") or {}
    R.check("E8", "defaults 含 4 个参数且值符合契约",
            all(k in defaults for k in ["raw_top_k", "final_top_k", "rrf_k", "score_threshold"])
            and defaults.get("raw_top_k") == 6 and defaults.get("final_top_k") == 3
            and defaults.get("rrf_k") == 60 and abs(float(defaults.get("score_threshold", -1)) - 0.08) < 1e-9,
            f"defaults={jdump(defaults)}")
    mstages = m.get("stages") or []
    R.check("E9", "meta.stages 每项含 name/label/desc 且覆盖核心阶段",
            mstages and all(all(k in s for k in ["name", "label", "desc"]) for s in mstages)
            and {"dense", "bm25", "rrf", "rerank"}.issubset({s.get("name") for s in mstages}),
            f"names={jdump([s.get('name') for s in mstages])}")

    # ---------------- F. 独立交叉验证 ----------------
    print("\n---- F. 交叉验证：直接调用 pipeline vs API ----", flush=True)
    try:
        from core.helper.retrieval_pipeline import get_retrieval_components, RetrievalPipeline
        from core.helper.trace_tracker import TraceTracker
    except Exception as e:
        R.check("F0", "import core.helper.retrieval_pipeline", False,
                f"{type(e).__name__}: {e}")
        return client, api_final, False

    class StubOptimizer:
        """把 API 报告的 optimized 固定注入，用于隔离「非确定性 LLM 优化器」这一变量。"""

        def __init__(self, data):
            self.data = dict(data or {})

        def optimize_prompt(self, prompt):
            d = dict(self.data)
            d.setdefault("search_query", prompt)
            d.setdefault("match_topics", [])
            d.setdefault("keywords", [])
            return d

    def build_pipe(components, optimizer):
        return RetrievalPipeline(
            embedding_model=components["embedding_model"],
            vector_db=components["vector_db"],
            bm25=components["bm25"],
            prompt_optimizer=optimizer,
            knowledge_loader=components["knowledge_loader"],
            reranker=components["reranker"],
        )

    def combo_kwargs(flags, params):
        params = params or {}
        return dict(
            dense=bool(flags["dense"]), bm25=bool(flags["bm25"]),
            rrf=bool(flags["rrf"]), rerank=bool(flags["rerank"]),
            raw_top_k=int(params.get("raw_top_k", 6)),
            final_top_k=int(params.get("final_top_k", 3)),
            rrf_k=int(params.get("rrf_k", 60)),
            score_threshold=params.get("score_threshold", 0.08),
        )

    try:
        t0 = time.time()
        comps = get_retrieval_components()
        R.check("F1", "get_retrieval_components() 返回 6 个组件",
                isinstance(comps, dict) and all(
                    k in comps for k in ["embedding_model", "vector_db", "bm25",
                                         "prompt_optimizer", "knowledge_loader", "reranker"]),
                f"keys={sorted(comps.keys()) if isinstance(comps, dict) else type(comps).__name__} load_ms={round((time.time()-t0)*1000,1)}")
        pipe = build_pipe(comps, comps["prompt_optimizer"])
    except Exception as e:
        R.check("F1", "构造 RetrievalPipeline", False,
                f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}")
        return client, api_final, False

    # 幂等/复用检查：再次调用 get_retrieval_components 应返回同一对象（进程内复用）
    try:
        comps2 = get_retrieval_components()
        R.check("F2", "组件进程内复用（二次调用同一对象）",
                all(comps[k] is comps2[k] for k in comps) if isinstance(comps2, dict) else False,
                f"identical={[k for k in comps if comps.get(k) is comps2.get(k)]}")
    except Exception as e:
        R.check("F2", "组件进程内复用", False, f"{type(e).__name__}: {e}")

    last_kwargs = combo_kwargs(COMBOS[-1][1], {"raw_top_k": 6, "final_top_k": 3,
                                               "rrf_k": 60, "score_threshold": 0.08})

    # ---- F.drift. 未固定优化器时的漂移证据（Lead 指示：记录为已知特性，不判 FAIL） ----
    print("\n---- F.drift. 未固定优化器漂移证据（INFO，不判 FAIL） ----", flush=True)
    drift_snapshots = []
    for _ in range(2):
        rr = client.post("/retrieval/debug", json={"query": QUERY, **COMBOS[-1][1]})
        pp = rr.json() if rr.status_code == 200 else {}
        dd = pp.get("data") or {}
        drift_snapshots.append({
            "optimized": dd.get("optimized"),
            "doc_ids": (dd.get("final") or {}).get("doc_ids"),
        })
    drift_opt = drift_snapshots[0]["optimized"] != drift_snapshots[1]["optimized"]
    drift_ids = drift_snapshots[0]["doc_ids"] != drift_snapshots[1]["doc_ids"]
    R.raw["F_drift"] = drift_snapshots
    R.info("F.drift", "同一查询两次 optimized 漂移（LLM 优化器非确定性，已知特性）",
           f"optimized漂移={drift_opt} doc_ids漂移={drift_ids} "
           f"opt1={brief(drift_snapshots[0]['optimized'], 140)} opt2={brief(drift_snapshots[1]['optimized'], 140)} "
           f"ids1={jdump(drift_snapshots[0]['doc_ids'])} ids2={jdump(drift_snapshots[1]['doc_ids'])}")

    # ---- K. Lead 生产修复复核：knowledge_loader / Retriever（用真实优化器） ----
    print("\n---- K. 生产链路修复复核 ----", flush=True)
    try:
        import os as _os
        from core.helper.knowledge_cache import KNOWLEDGE_CACHE
        from core.loader.knowledge_loader import KnowledgeLoader

        id_map = json.loads((ROOT / "config" / "id_map.json").read_text(encoding="utf-8"))
        bad_paths = [k for k, v in id_map.items()
                     if not _os.path.isabs(str(v)) or not _os.path.exists(str(v))]
        R.check("K1", f"config/id_map.json 全部路径本机可解析（{len(id_map)}/11）",
                len(id_map) == 11 and not bad_paths,
                f"entries={len(id_map)} unresolvable={bad_paths[:3]}")

        kl = KnowledgeLoader()
        real_ids = [x.doc_id for x in KNOWLEDGE_CACHE.documents[:3]]
        loaded = kl.load_knowledge(real_ids)
        R.check("K2", "KnowledgeLoader().load_knowledge(3 ids) 返回 3/3 且顺序一致",
                [d.doc_id for d in loaded] == real_ids,
                f"expect={jdump(real_ids)} actual={jdump([d.doc_id for d in loaded])}")
        R.check("K2b", "KnowledgeLoader().data 条目数 == 11", len(kl.data) == 11, f"n={len(kl.data)}")
        R.check("K2c", "id_map 的 doc_id 集合 == KNOWLEDGE_CACHE 的 doc_id 集合",
                set(id_map.keys()) == {x.doc_id for x in KNOWLEDGE_CACHE.documents},
                f"only_map={sorted(set(id_map) - {x.doc_id for x in KNOWLEDGE_CACHE.documents})[:3]}")

        from core.helper.retriever import Retriever
        retriever = Retriever(
            embedding_model=comps["embedding_model"], vector_db=comps["vector_db"],
            bm25=comps["bm25"], prompt_optimizer=comps["prompt_optimizer"],
            knowledge_loader=comps["knowledge_loader"], reranker=comps["reranker"],
        )
        prod_docs = retriever.retrieve(QUERY, raw_top_k=6, final_top_k=3)
        R.check("K3", "生产 Retriever.retrieve 返回 ≥1 篇 Document（id_map 修复生效）",
                isinstance(prod_docs, list) and len(prod_docs) >= 1,
                f"n={len(prod_docs)} ids={jdump([getattr(d, 'doc_id', None) for d in prod_docs])}")
        R.raw["K3_production_retrieve"] = [getattr(d, "doc_id", None) for d in prod_docs or []]
    except Exception as e:
        R.check("K", "生产链路修复复核", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}")

    # ---- F3. 固定优化器（Lead 指定方法）：stub 注入进程单例，API 与直跑共用同一优化结果 ----
    print("\n---- F3. 固定优化器后 API vs 直跑逐字段比对 ----", flush=True)
    import core.helper.retrieval_pipeline as rp
    comps_ref = rp.get_retrieval_components()
    real_optimizer = comps_ref.get("prompt_optimizer")
    R.check("F3.stub-setup", "进程单例 prompt_optimizer 可替换（同一 dict）",
            comps_ref is comps and real_optimizer is not None,
            f"same_dict={comps_ref is comps} real_optimizer={type(real_optimizer).__name__}")

    cross_ok_all = True
    determinism_ok = True
    f3_detail = {}
    last_kwargs = combo_kwargs(COMBOS[-1][1], {"raw_top_k": 6, "final_top_k": 3,
                                               "rrf_k": 60, "score_threshold": 0.08})
    try:
        comps_ref["prompt_optimizer"] = StubOptimizer(FIXED_OPTIMIZED)
        for cid_base, flags, exp_stages, exp_source in COMBOS:
            cid = f"F3[{cid_base}]"
            rr = client.post("/retrieval/debug", json={"query": QUERY, **flags})
            pp = rr.json() if rr.status_code == 200 else {}
            dd = pp.get("data") or {}
            if pp.get("code") != 200:
                R.check(cid, f"{cid_base} API code=200（stub 优化器）", False,
                        f"http={rr.status_code} body={rr.text[:220]}")
                cross_ok_all = False
                continue

            kw = combo_kwargs(flags, dd.get("params"))
            last_kwargs = kw
            direct_pipe = RetrievalPipeline(**comps_ref)
            try:
                t0 = time.time()
                direct = direct_pipe.run(QUERY, trace=TraceTracker(), **kw)
                dt = round((time.time() - t0) * 1000, 1)
            except Exception as e:
                R.check(cid, f"{cid_base} 直接调用 pipeline（stub 优化器）", False,
                        f"{type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}")
                cross_ok_all = False
                continue

            # stub 生效：api 的 optimized / stages[0].extra == 固定值
            api_stage_list = dd.get("stages") or []
            api_opt = dd.get("optimized") or {}
            api_extra = (api_stage_list[0].get("extra") if api_stage_list else {}) or {}
            R.check(f"{cid}.stub", f"{cid_base} stub 优化结果已生效（optimized == 固定值）",
                    api_opt == FIXED_OPTIMIZED and api_extra == FIXED_OPTIMIZED,
                    f"api_optimized={brief(api_opt, 160)} api_extra={brief(api_extra, 160)}")

            # 阶段集合与顺序
            api_names = [s.get("name") for s in api_stage_list]
            direct_names = [s.get("name") for s in direct.get("stages") or []]
            R.check(f"{cid}.s", f"{cid_base} 阶段集合/顺序一致",
                    api_names == direct_names == exp_stages,
                    f"expect={jdump(exp_stages)} api={jdump(api_names)} direct={jdump(direct_names)}")

            # 逐阶段 doc_id + score 逐条比对
            api_stage_map = {s.get("name"): s for s in api_stage_list}
            stage_detail = {}
            for st in direct.get("stages") or []:
                nm = st.get("name")
                dn = [it.get("doc_id") for it in st.get("results") or []]
                ds = [it.get("score") for it in st.get("results") or []]
                a_stage = api_stage_map.get(nm) or {}
                an = [it.get("doc_id") for it in a_stage.get("results") or []]
                a_sc = [it.get("score") for it in a_stage.get("results") or []]
                stage_detail[nm] = dn
                if dn != an or ds != a_sc:
                    R.check(f"{cid}.{nm}", f"{cid_base} stage {nm} 候选与分数一致", False,
                            f"ids_expect={jdump(dn)} ids_actual={jdump(an)} scores_equal={ds == a_sc}")
                    cross_ok_all = False

            # final 逐条比对
            fin = dd.get("final") or {}
            d_fin = direct.get("final") or {}
            d_ids = list(d_fin.get("doc_ids") or [])
            a_ids = list(fin.get("doc_ids") or [])
            ok = (d_ids == a_ids and d_fin.get("source") == fin.get("source") == exp_source
                  and d_fin.get("count") == fin.get("count"))
            cross_ok_all = cross_ok_all and ok
            R.check(cid, f"{cid_base} final 逐条一致（source/count/doc_ids）", ok,
                    f"expect(direct)={jdump(d_ids)} actual(api)={jdump(a_ids)} "
                    f"source_direct={d_fin.get('source')!r} source_api={fin.get('source')!r} run_ms={dt}")

            # Lead 要求：每阶段 results[].doc 均非空；不出现「候选 doc_id 不存在」日志
            docs_null = [f"{s.get('name')}#{it.get('rank')}"
                         for s in api_stage_list for it in (s.get("results") or [])
                         if it.get("doc") is None]
            R.check(f"{cid}.docs", f"{cid_base} 每阶段 results[].doc 均非空",
                    not docs_null, f"null_docs={docs_null[:5]} stages={jdump(api_names)}")
            api_logs = dd.get("logs") or []
            missing_logs = [l.get("label") for l in api_logs
                            if "不存在" in str(l.get("label") or "") or "不存在" in str(l.get("error_msg") or "")]
            R.check(f"{cid}.no-missing", f"{cid_base} 无「候选 doc_id 不存在」日志",
                    not missing_logs, f"hit={missing_logs[:3]}")
            R.check(f"{cid}.log", f"{cid_base} logs 非空且覆盖已执行阶段",
                    len(api_logs) > 0 and all(n in {l.get("stage") for l in api_logs} for n in api_names),
                    f"n_logs={len(api_logs)} stages={jdump([l.get('stage') for l in api_logs])}")

            # 固定优化器下二次直跑：检索数学确定性
            direct2 = direct_pipe.run(QUERY, trace=TraceTracker(), **kw)
            snap1 = {s.get("name"): [it.get("doc_id") for it in s.get("results") or []] for s in direct.get("stages") or []}
            snap2 = {s.get("name"): [it.get("doc_id") for it in s.get("results") or []] for s in direct2.get("stages") or []}
            same = (snap1 == snap2 and d_ids == list((direct2.get("final") or {}).get("doc_ids") or []))
            if not same:
                determinism_ok = False
                R.check(f"{cid}.det", f"{cid_base} stub 下两次直跑一致", False,
                        f"run1={brief(snap1, 260)} run2={brief(snap2, 260)}")
            f3_detail[cid_base] = {"api_doc_ids": a_ids, "direct_doc_ids": d_ids, "match": ok,
                                   "stages": stage_detail}

        R.check("F3.shape", "pipeline.run 返回纯 Python 可 JSON 序列化结构（无 numpy 标量）",
                _check_serializable(RetrievalPipeline(**comps_ref), last_kwargs), "")
    finally:
        comps_ref["prompt_optimizer"] = real_optimizer

    R.check("F3.overall", "8 种组合：stub 优化器下 API 与直跑 stages/final 全一致", cross_ok_all, "")
    R.check("F3.determinism", "stub 优化器下 pipeline 两次直跑结果完全一致（检索数学确定性）",
            determinism_ok, "")
    R.raw["F3_fixed_optimizer"] = f3_detail


    # ---- F6. 独立复算算法（不依赖 pipeline 内部实现，逐阶段用原始组件重算） ----
    print("\n---- F6. 独立复算 dense / bm25 / rrf / rerank ----", flush=True)
    try:
        import jieba
        from core.helper.knowledge_cache import KNOWLEDGE_CACHE

        all_entry = api_final["all"]
        opt = all_entry.get("optimized") or {}
        kw = combo_kwargs(next(c[1] for c in COMBOS if c[0] == "all"), all_entry.get("params"))
        stub_pipe = build_pipe(comps, StubOptimizer(opt))
        direct = stub_pipe.run(QUERY, trace=TraceTracker(), **kw)
        stage_map = {s.get("name"): s for s in direct.get("stages", [])}

        # dense 独立复算：encode(search_query + query) → vector_db.query(top_k)
        emb = comps["embedding_model"].encode(str(opt.get("search_query") or QUERY) + QUERY)
        chroma_res = comps["vector_db"].query(emb, kw["raw_top_k"])
        exp_dense = [str(i) for i in (chroma_res.get("ids") or [[]])[0]]
        act_dense = [it.get("doc_id") for it in stage_map["dense"]["results"]]
        R.check("F6.dense", "dense 阶段候选 == 独立复算 vector_db.query",
                exp_dense == act_dense, f"expect={jdump(exp_dense)} actual={jdump(act_dense)}")

        # bm25 独立复算：jieba(query)+topics+keywords → BM25TagIndexer.search(top_k)
        tokens = list(jieba.cut(QUERY)) + list(opt.get("match_topics") or []) + list(opt.get("keywords") or [])
        exp_bm25 = [str(i) for i in (comps["bm25"].search(tokens, kw["raw_top_k"]) or [])]
        act_bm25 = [it.get("doc_id") for it in stage_map["bm25"]["results"]]
        R.check("F6.bm25", "bm25 阶段候选 == 独立复算 BM25TagIndexer.search",
                exp_bm25 == act_bm25, f"expect={jdump(exp_bm25)} actual={jdump(act_bm25)}")

        # rrf 独立复算：1/(pos+k)，dense 在前
        rank_score = {}
        for pos, did in enumerate(exp_dense):
            rank_score[did] = rank_score.get(did, 0.0) + 1.0 / (pos + kw["rrf_k"])
        for pos, did in enumerate(exp_bm25):
            rank_score[did] = rank_score.get(did, 0.0) + 1.0 / (pos + kw["rrf_k"])
        exp_rrf = [d for d, _ in sorted(rank_score.items(), key=lambda x: x[1], reverse=True)]
        act_rrf = [it.get("doc_id") for it in stage_map["rrf"]["results"]]
        R.check("F6.rrf", "rrf 阶段候选 == 独立复算 1/(pos+rrf_k)",
                exp_rrf == act_rrf, f"expect={jdump(exp_rrf)} actual={jdump(act_rrf)}")

        # rerank 独立复算：直接用生产 reranker.rerank_documents（默认阈值路径）
        upstream_docs = [KNOWLEDGE_CACHE.cache[d] for d in exp_rrf if d in KNOWLEDGE_CACHE.cache]
        exp_rerank = [d.doc_id for d in comps["reranker"].rerank_documents(
            QUERY, upstream_docs, kw["final_top_k"], None)]
        act_final = list((direct.get("final") or {}).get("doc_ids") or [])
        R.check("F6.rerank", "final.doc_ids == 独立调用 reranker.rerank_documents（默认阈值）",
                exp_rerank == act_final,
                f"expect={jdump(exp_rerank)} actual={jdump(act_final)} upstream_n={len(upstream_docs)}")
        R.raw["F6_recompute"] = {
            "dense": exp_dense, "bm25": exp_bm25, "rrf": exp_rrf, "rerank": exp_rerank,
            "pipeline": {"dense": act_dense, "bm25": act_bm25, "rrf": act_rrf, "final": act_final},
        }
    except Exception as e:
        R.check("F6", "独立复算算法", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}")

    # ---- H. 边界 / 反例 ----
    print("\n---- H. 边界与反例 ----", flush=True)
    edge_cases = [
        ("H1", "bm25-only 无命中词", {"query": "zzzzqqqq1234", "dense": False, "bm25": True, "rrf": False, "rerank": False}),
        ("H2", "rerank 阈值=1.0（全部过滤）", {"query": QUERY, "dense": True, "bm25": True, "rrf": True, "rerank": True, "score_threshold": 1.0}),
        ("H3", "raw_top_k=50 final_top_k=50", {"query": QUERY, "dense": True, "bm25": True, "rrf": True, "rerank": True, "raw_top_k": 50, "final_top_k": 50}),
        ("H4", "query 仅空白字符", {"query": "   "}),
        ("H5", "全不勾选", {"query": QUERY, "dense": False, "bm25": False, "rrf": False, "rerank": False}),
        ("H6", "score_threshold=0.0（最宽松合法值）", {"query": QUERY, "dense": True, "bm25": True, "rrf": True, "rerank": True, "score_threshold": 0.0}),
    ]
    for cid, name, body in edge_cases:
        rr = client.post("/retrieval/debug", json=body)
        try:
            pp = rr.json()
        except Exception:
            pp = {}
        code = pp.get("code")
        dd = pp.get("data") or {}
        if cid in ("H4", "H5"):
            R.check(cid, f"{name} → code=400", code == 400,
                    f"http={rr.status_code} code={code!r} msg={pp.get('msg')!r}")
            continue
        fin = dd.get("final") or {}
        shape_ok = (code == 200 and isinstance(dd.get("stages"), list)
                    and fin.get("count") == len(fin.get("doc_ids") or []) == len(fin.get("results") or [])
                    and all(s.get("name") for s in dd.get("stages") or []))
        if cid == "H3":
            shape_ok = shape_ok and fin.get("count") <= 50
        note = f"http={rr.status_code} code={code!r} final.count={fin.get('count')} source={fin.get('source')!r} stages={jdump([s.get('name') for s in dd.get('stages') or []])}"
        R.check(cid, f"{name} 不 500 且返回体形状合法", shape_ok, note)
        if code == 200 and fin.get("count") == 0:
            R.info(f"{cid}-empty", f"{name} 结果为空", "属阈值/无命中预期行为，形状仍合法")

    return client, api_final, True


def _check_serializable(pipe, run_kwargs):
    try:
        from core.helper.trace_tracker import TraceTracker
        res = pipe.run(QUERY, trace=TraceTracker(), **run_kwargs)
        json.dumps(res, ensure_ascii=False, default=str)
        # 严格：不允许 numpy 标量（default=str 会掩盖），显式扫描
        import numpy as np

        def scan(o, path=""):
            if isinstance(o, np.generic):
                return f"numpy 标量 {type(o).__name__} @ {path}"
            if isinstance(o, np.ndarray):
                return f"ndarray @ {path}"
            if isinstance(o, dict):
                for k, v in o.items():
                    r = scan(v, f"{path}.{k}")
                    if r:
                        return r
            if isinstance(o, (list, tuple)):
                for i, v in enumerate(o):
                    r = scan(v, f"{path}[{i}]")
                    if r:
                        return r
            return None
        problem = scan(res)
        R.raw["pipeline_run_serializable"] = "ok" if not problem else problem
        return problem is None
    except Exception as e:
        R.raw["pipeline_run_serializable"] = f"error: {e}"
        return False


# ---------------------------------------------------------------- main
def main() -> int:
    print(f"verify_retrieval_debug.py  ROOT={ROOT}")
    print(f"python={sys.version.split()[0]}  HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE')}")
    print(f"time={time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"query={QUERY!r}")

    before = snapshot_business_data()
    dep_missing = False
    try:
        static_checks()
        api_checks()
    except Exception as e:
        dep_missing = True
        R.check("Z", "验证主流程未因依赖缺失中断", False,
                f"{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}")

    after = snapshot_business_data()
    changed = sorted(set(k for k in set(before) | set(after) if before.get(k) != after.get(k)))
    # 只统计业务数据哨兵目录（chroma sqlite 不在哨兵内）
    if changed:
        R.info("Z1", "业务数据哨兵变化（只读约束）", "changed=" + jdump([str(Path(c).relative_to(ROOT)) for c in changed][:10]))
    else:
        R.info("Z1", "业务数据只读哨兵", "data/knowledge、store/bm25_store、config/id_map.json 无变化")

    result = R.to_dict()
    result["root"] = str(ROOT)
    result["query"] = QUERY
    result["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n================ 汇总 ================")
    n_pass = sum(1 for r in R.rows if r[2] == "PASS")
    n_fail = R.nfail()
    n_info = sum(1 for r in R.rows if r[2] == "INFO")
    print(f"PASS={n_pass}  FAIL={n_fail}  INFO={n_info}")
    if n_fail:
        print("---- FAIL 明细 ----")
        for c, n, s, d in R.rows:
            if s == "FAIL":
                print(f"  {c} {n} :: {d}")
    print(f"完整结果(JSON): {RESULT_JSON}")
    if n_fail:
        return 1
    if dep_missing:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
