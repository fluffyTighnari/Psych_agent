"""检索文本构造的唯一实现（dense / BM25 / rerank 三处共用，避免口径漂移）。

为什么单独成模块：
- 向量库的「文档编码文本」在建库时决定，检索时的「查询编码文本」在 pipeline 里决定，
  两边必须成对演进；reranker 的输入文本又同时被 `core/helper/reranker.py` 与
  `core/helper/retrieval_pipeline.py` 使用。集中一处可避免改了一边忘了另一边。

各 variant 的取舍（数值见 docs/rag_optimization_report.md 的消融表）：
- dense 文档侧 `problem_solution`：周记只取「问题定义 + 解决方案」，日记取「摘要 + 正文前段」。
  理由：向量检索要匹配的是「用户的困扰」，而不是铺垫性的 analysis。
- dense 查询侧：原始提问 + search_query + 两篇 HyDE（经历式 / 原则式）分别编码后加权平均归一化。
  理由：单条查询向量无法同时贴近「短口语日记」与「长结构化周记」两种文档形态。
- BM25 查询侧：原始提问与 distinctive_terms 给高权重，泛化的 keywords/topics 给低权重，
  避免扩展词把原始意图稀释掉。
- rerank 输入：摘要 + 关键词 + 周记 problem/solution（日记取正文前段）。
"""
from __future__ import annotations

from core.helper.retrieval_config import (
    BM25_QUERY_WEIGHTS,
    DENSE_DOC_VARIANT,
    DENSE_QUERY_WEIGHTS,
    RERANK_INPUT_VARIANT,
)

# ===================== dense：文档编码文本 =====================


def dense_doc_text(doc, variant: str = DENSE_DOC_VARIANT) -> str:
    """把 Document 转成「会被写入向量库」的文本。"""
    doc_type = getattr(doc, "doc_type", "")
    title = getattr(doc, "title", "") or ""
    summary = getattr(doc, "summary", "") or ""
    content = getattr(doc, "content", "") or ""

    if variant == "legacy":
        # v1 行为：weekly = title + summary，daily = summary
        if doc_type == "weekly":
            return f"{title}\n\n{summary}"
        return summary

    if variant == "title_summary_kw":
        kw = "、".join(getattr(doc, "keywords", None) or [])
        tp = "、".join(getattr(doc, "topic", None) or [])
        return f"{title}\n{summary}\n关键词：{kw}\n主题：{tp}"

    if variant == "problem_solution":
        if doc_type == "weekly":
            parts = [title, summary, getattr(doc, "problem", "") or "", getattr(doc, "solution", "") or ""]
            return "\n".join(p for p in parts if p)
        parts = [title, summary, content[:300]]
        return "\n".join(p for p in parts if p)

    if variant == "rich":
        if doc_type == "weekly":
            parts = [title, summary, getattr(doc, "problem", "") or "", getattr(doc, "solution", "") or ""]
            return "\n".join(p for p in parts if p)
        parts = [title, summary, content[:400]]
        return "\n".join(p for p in parts if p)

    if variant == "full":
        return f"{title}\n{summary}\n{content[:800]}"

    raise KeyError(f"未知 dense 文档规格: {variant}")


# ===================== dense：查询编码文本 =====================

BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def dense_query_texts(query: str, optimized: dict, *, use_hyde: bool = True,
                      weights: dict | None = None, instruction: bool = True) -> list[tuple[str, float]]:
    """返回 [(待编码文本, 权重), ...]；权重为 0 的项会被跳过。

    HyDE 的两个假设文档分别对齐「经历类(daily)」与「原则类(weekly)」笔记的写法，
    使同一条口语化提问在两种文档形态上都有语义落点。
    """
    opt = optimized or {}
    w = dict(DENSE_QUERY_WEIGHTS if weights is None else weights)
    items: list[tuple[str, float]] = []
    prefix = BGE_QUERY_INSTRUCTION if instruction else ""

    q = prefix + (query or "")
    if w.get("query"):
        items.append((q, float(w["query"])))

    sq = (opt.get("search_query") or "").strip()
    if sq and w.get("search_query"):
        items.append((prefix + sq, float(w["search_query"])))

    if use_hyde:
        he = (opt.get("hyde_experience") or "").strip()
        hp = (opt.get("hyde_principle") or "").strip()
        if he and w.get("hyde_experience"):
            items.append((he, float(w["hyde_experience"])))
        if hp and w.get("hyde_principle"):
            items.append((hp, float(w["hyde_principle"])))
    return items


# ===================== BM25：查询侧词项与权重 =====================


def _repeat(tokens, weight: float) -> list[str]:
    """用「重复次数」表达 BM25 查询词权重（get_scores 对 query 词频是线性的）。

    权重为整数倍数（见 retrieval_config.BM25_QUERY_WEIGHTS），0 表示不参与。
    """
    if not tokens or weight <= 0:
        return []
    return list(tokens) * max(1, int(round(weight)))


def bm25_query_tokens(query: str, optimized: dict, weights: dict | None = None) -> list[str]:
    """构造 BM25 查询词项序列（含按权重重复）。

    与 v1 的差别：v1 是 ``jieba(query) + match_topics + keywords`` 各算一次；
    这里把「用户原话」保持主导、把 LLM 扩展词压到半权重，直接对症
    「扩展词稀释原始意图 / 让候选文档获得虚假匹配优势」。
    权重表见 ``retrieval_config.BM25_QUERY_WEIGHTS``（消融数据见优化报告）。
    """
    import jieba

    opt = optimized or {}
    w = dict(BM25_QUERY_WEIGHTS if weights is None else weights)

    tokens: list[str] = []
    tokens += _repeat([t for t in jieba.cut(query or "") if t.strip()], w.get("query", 0))
    tokens += _repeat(
        [t for t in jieba.cut(" ".join(opt.get("distinctive_terms") or [])) if t.strip()],
        w.get("distinctive", 0),
    )
    tokens += _repeat(
        [t for t in jieba.cut(opt.get("search_query") or "") if t.strip()],
        w.get("search_query", 0),
    )
    kw = [str(k).lower() for k in (opt.get("keywords") or [])]
    tokens += _repeat(kw, w.get("keywords", 0))
    topics = [str(t).strip().lower() for t in (opt.get("match_topics") or [])]
    tokens += _repeat(topics, w.get("topics", 0))
    return tokens


# ===================== rerank：交叉编码器输入文本 =====================


def rerank_input_text(doc, variant: str = RERANK_INPUT_VARIANT) -> str:
    """cross-encoder 的文档侧输入。"""
    doc_type = getattr(doc, "doc_type", "")
    summary = getattr(doc, "summary", "") or ""
    title = getattr(doc, "title", "") or ""
    content = getattr(doc, "content", "") or ""
    kw = "、".join(getattr(doc, "keywords", None) or [])

    if variant == "legacy":
        parts = [summary]
        if doc_type == "weekly":
            parts += [getattr(doc, "problem", "") or "", getattr(doc, "solution", "") or ""]
        else:
            parts += [content[:800]]
        return "\n".join(parts)

    if variant == "with_kw":
        parts = [summary, f"关键词：{kw}"]
        if doc_type == "weekly":
            parts += [getattr(doc, "problem", "") or "", getattr(doc, "solution", "") or ""]
        else:
            parts += [content[:800]]
        return "\n".join(p for p in parts if p)

    if variant == "problem_solution":
        parts = [summary]
        if doc_type == "weekly":
            parts += [getattr(doc, "problem", "") or "", getattr(doc, "solution", "") or ""]
        else:
            parts += [content[:400]]
        return "\n".join(p for p in parts if p)

    if variant == "full":
        parts = [title, summary]
        if doc_type == "weekly":
            parts += [getattr(doc, "problem", "") or "", getattr(doc, "analysis", "") or "",
                      getattr(doc, "solution", "") or ""]
        else:
            parts += [content[:1500]]
        return "\n".join(p for p in parts if p)

    raise KeyError(f"未知 rerank 输入规格: {variant}")
