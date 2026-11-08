"""precompute 用到的文本构造实现（复制自 core/helper/retrieval_text.py 的实验版本，
便于在不动生产代码的情况下先做消融；最终结论会同步回 core/helper/retrieval_text.py）。"""
from __future__ import annotations

INSTRUCT = "为这个句子生成表示以用于检索相关文章："


def doc_text(doc, variant: str) -> str:
    if variant == "legacy":
        if doc.doc_type == "weekly":
            return f"{doc.title}\n\n{doc.summary}"
        return doc.summary or ""
    if variant == "title_summary_kw":
        kw = "、".join(doc.keywords or [])
        tp = "、".join(doc.topic or [])
        return f"{doc.title}\n{doc.summary}\n关键词：{kw}\n主题：{tp}"
    if variant == "problem_solution":
        if doc.doc_type == "weekly":
            return f"{doc.title}\n{doc.summary}\n{doc.problem}\n{doc.solution}"
        return f"{doc.title}\n{doc.summary}\n{(doc.content or '')[:300]}"
    if variant == "rich":
        if doc.doc_type == "weekly":
            return f"{doc.title}\n{doc.summary}\n{doc.problem}\n{doc.solution}"
        return f"{doc.title}\n{doc.summary}\n{(doc.content or '')[:400]}"
    if variant == "full":
        return f"{doc.title}\n{doc.summary}\n{(doc.content or '')[:800]}"
    raise KeyError(variant)


def query_text(q: str, opt: dict, kind: str) -> str:
    sq = opt.get("search_query") or ""
    kw = "、".join(opt.get("keywords") or [])
    tp = "、".join(opt.get("match_topics") or [])
    if kind == "raw":
        return q
    if kind == "sq":
        return sq
    if kind == "raw_sq":
        return f"{sq} {q}"
    if kind == "raw_sq_kw":
        return f"{sq} {q} {kw} {tp}"
    if kind == "instruct_raw_sq":
        return f"{INSTRUCT}{q} {sq}"
    if kind == "instruct_raw":
        return f"{INSTRUCT}{q}"
    if kind in ("hyde_experience", "hyde_principle"):
        return opt.get(kind) or ""
    raise KeyError(kind)


def rerank_text(doc, variant: str) -> str:
    if variant == "legacy":
        parts = [doc.summary or ""]
        if doc.doc_type == "weekly":
            parts += [doc.problem or "", doc.solution or ""]
        else:
            parts += [(doc.content or "")[:800]]
        return "\n".join(parts)
    if variant == "with_kw":
        parts = [doc.summary or "", "关键词：" + "、".join(doc.keywords or [])]
        if doc.doc_type == "weekly":
            parts += [doc.problem or "", doc.solution or ""]
        else:
            parts += [(doc.content or "")[:800]]
        return "\n".join(parts)
    if variant == "problem_solution":
        parts = [doc.summary or ""]
        if doc.doc_type == "weekly":
            parts += [doc.problem or "", doc.solution or ""]
        else:
            parts += [(doc.content or "")[:400]]
        return "\n".join(parts)
    if variant == "full":
        parts = [doc.title or "", doc.summary or ""]
        if doc.doc_type == "weekly":
            parts += [doc.problem or "", doc.analysis or "", doc.solution or ""]
        else:
            parts += [(doc.content or "")[:1500]]
        return "\n".join(parts)
    raise KeyError(variant)
