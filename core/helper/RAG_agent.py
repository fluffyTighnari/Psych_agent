from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from config.model_config import GLOBAL_MODEL, get_langchain_llm
from config.prompt_config import RAG_system_prompt, RAG_human_prompt
from core.helper import retrieval_config as RC

# ===================== 重构分层RAG Prompt =====================
RAG_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
    (
        "system",
        RAG_system_prompt
    ),
    (
        "human",
        RAG_human_prompt
    )
])


def format_principle(doc_list) -> str:
    """渲染周记Principle：只保留问题、分析、解决方案，剔除冗余content，并附ID供引用"""
    blocks = []
    for idx, doc in enumerate([doc for doc in doc_list if doc.doc_type == "weekly"], 1):
        emotion = doc.emotion if isinstance(doc.emotion, dict) else {}
        topic_text = ",".join(doc.topic) if isinstance(doc.topic, list) else str(doc.topic or "")
        block = f"【心理原则{idx}】ID:{doc.doc_id}\n"
        block += f"核心困扰：{doc.problem or ''}\n"
        block += f"深层心理分析：{doc.analysis or ''}\n"
        block += f"对应调节方案：{doc.solution or ''}\n"
        block += f"关联情绪：{emotion.get('primary', '未标注')} 相关主题：{topic_text}\n"
        blocks.append(block)
    if not blocks:
        return "暂无用户沉淀的心理调节原则"
    return "\n---\n".join(blocks)


def format_experience(doc_list) -> str:
    """渲染日记Experience：精简情绪+完整日记，并附ID供引用"""
    blocks = []
    for idx, doc in enumerate([doc for doc in doc_list if doc.doc_type == "daily"], 1):
        emotion = doc.emotion if isinstance(doc.emotion, dict) else {}
        block = f"【过往经历{idx}】ID:{doc.doc_id}\n"
        block += f"记录内容：{doc.content}"
        block += f"记录时间：{doc.date if doc.date else '未标注日期'}\n"
        block += f"当时核心情绪：{emotion.get('primary', '未标注')}（强度{emotion.get('intensity', '未标注')}）\n"
        blocks.append(block)
    if not blocks:
        return "暂无相似过往经历记录"
    return "\n---\n".join(blocks)


class PsychRAGAgent:
    def __init__(
        self,
        pipeline,
        chat_model: BaseChatModel | None = None,
    ):
        self.pipeline = pipeline
        self.llm = chat_model or get_langchain_llm(GLOBAL_MODEL.chat)
        # 改造链路：拆分上下文入参
        self.rag_chain = (
            {
                "chat_history": lambda inputs: inputs.get("chat_history", "暂无当前会话对话历史"),
                "memory_context": lambda inputs: inputs.get("memory_context", "暂无相关历史会话记录"),
                "principle_knowledge": lambda inputs: format_principle(inputs["docs"]),
                "experience_knowledge": lambda inputs: format_experience(inputs["docs"]),
                "query": lambda inputs: inputs["query"],
                "situation": lambda inputs: inputs.get("situation", "未提供具体情境"),
                "guided_reasons": lambda inputs: inputs.get("guided_reasons", "暂无已完成推理"),
                "attached_context": lambda inputs: inputs.get("attached_context", "无"),
            }
            | RAG_PROMPT_TEMPLATE
            | self.llm
            | StrOutputParser()
        )

    def _split_query(self, query: str):
        """按【具体情境】拆出问题描述与可选情境，检索只用问题描述。"""
        q = query or ""
        if "【具体情境】" in q:
            problem, situation = q.split("【具体情境】", 1)
            return problem.strip(), situation.strip()
        return q.strip(), ""

    def retrieve(self, query: str, raw_top_k=RC.DEFAULT_RAW_TOP_K,
                 final_top_k=RC.DEFAULT_FINAL_TOP_K) -> list:
        """纯检索：仅用问题描述（自动剥离【具体情境】，避免情境稀释召回），
        返回重排后的 Document 列表。供 retrieve_knowledge_tool 按需调用。
        """
        problem, _ = self._split_query(query)
        return self.pipeline.retrieve_documents(problem, raw_top_k, final_top_k)

    def retrieve_scored(self, query: str, raw_top_k=RC.DEFAULT_RAW_TOP_K,
                        final_top_k=RC.DEFAULT_FINAL_TOP_K, **kwargs) -> dict:
        """带分数的纯检索（阶段 4-C）：返回 ``{"query","docs","scores"}``。

        ``scores`` 是 {doc_id: cross-encoder 概率}，供 Evaluator 判 evidence_gap；
        ``kwargs`` 原样透传给 RetrievalPipeline.run（补救时用于扩 raw_top_k / rerank_pool）。
        """
        problem, _ = self._split_query(query)
        docs, scores = self.pipeline.retrieve_documents_with_scores(
            problem, raw_top_k, final_top_k, **kwargs
        )
        return {"query": problem, "docs": docs, "scores": scores}

    def retrieve_multi(self, queries, raw_top_k=RC.DEFAULT_RAW_TOP_K,
                       final_top_k=RC.DEFAULT_FINAL_TOP_K, **kwargs) -> dict:
        """多子查询检索 → 合并去重（阶段 4-C「分解查询重检」）。

        合并口径（可解释、无隐式阈值）：
        - 同一 doc 被多个子查询命中，说明它覆盖多个方面 → ``hits`` 计数；
        - 排序键 = ``最高 cross-encoder 分 + 0.05 × (hits-1)``（封顶 1.0），
          同分时按「首次出现的排名」稳定排序。
        单查询时等价于 ``retrieve_scored``，不产生额外开销。

        返回 ``{"query","queries","docs","scores","per_query"}``。
        """
        valid: list[str] = []
        for q in (queries or []):
            s = str(q).strip()
            if s and s not in valid:
                valid.append(s)
        if not valid:
            return {"query": "", "queries": [], "docs": [], "scores": {}, "per_query": []}
        if len(valid) == 1:
            res = self.retrieve_scored(valid[0], raw_top_k, final_top_k, **kwargs)
            res.update({"queries": valid,
                        "per_query": [{"query": valid[0],
                                       "doc_ids": [d.doc_id for d in res["docs"]]}]})
            return res

        merged: dict[str, dict] = {}
        per_query = []
        for q in valid:
            res = self.retrieve_scored(q, raw_top_k, final_top_k, **kwargs)
            per_query.append({"query": q, "doc_ids": [d.doc_id for d in res["docs"]]})
            for rank, doc in enumerate(res["docs"]):
                doc_id = str(getattr(doc, "doc_id", ""))
                item = merged.get(doc_id)
                score = float(res["scores"].get(doc_id, 0.0))
                if item is None:
                    merged[doc_id] = {"doc": doc, "best": score, "hits": 1, "first_rank": rank}
                else:
                    item["best"] = max(item["best"], score)
                    item["hits"] += 1
                    item["first_rank"] = min(item["first_rank"], rank)

        def sort_key(pair):
            item = pair[1]
            total = min(1.0, item["best"] + 0.05 * (item["hits"] - 1))
            return (total, -item["first_rank"])

        ordered = sorted(merged.items(), key=sort_key, reverse=True)[:final_top_k]
        docs = [item["doc"] for _, item in ordered]
        scores = {doc_id: round(float(item["best"]), 6) for doc_id, item in ordered}
        return {"query": valid[0], "queries": valid, "docs": docs,
                "scores": scores, "per_query": per_query}

    def generate(self, query: str, doc_list: list, memory_context: str = "",
                 chat_history: str = "", guided_reasons: str = "",
                 attached_context: str = "") -> Dict[str, Any]:
        """纯生成：基于给定文档（可为空列表=本轮未检索、纯共情对话）+上下文生成回复。
        本方法不再触发检索，知识证据由调用方（retrieve_knowledge_tool）准备。
        """
        problem, situation = self._split_query(query)
        doc_list = doc_list or []
        mem_ctx = memory_context if memory_context else "暂无相关历史会话记录"
        chat_ctx = chat_history if chat_history else "暂无当前会话对话历史"
        reason_ctx = guided_reasons if guided_reasons else "暂无已完成推理"
        # 执行RAG链路，传入文档+问题+情境+记忆上下文+当前对话历史+已完成推理
        answer = self.rag_chain.invoke({
            "docs": doc_list,
            "query": problem,
            "situation": situation,
            "memory_context": mem_ctx,
            "chat_history": chat_ctx,
            "guided_reasons": reason_ctx,
            "attached_context": attached_context or "无",
        })
        # 拼接完整prompt用于日志记录
        principle_ctx = format_principle(doc_list)
        exp_ctx = format_experience(doc_list)
        full_prompt = RAG_PROMPT_TEMPLATE.format(
            chat_history=chat_ctx,
            memory_context=mem_ctx,
            principle_knowledge=principle_ctx,
            experience_knowledge=exp_ctx,
            query=problem,
            situation=situation,
            guided_reasons=reason_ctx,
            attached_context=attached_context or "无",
        )
        #rag_agent回复日志
        return {
            "answer": answer,
            "documents": doc_list,
            "prompt": full_prompt,
            "raw": {
                "doc_names": [d.title for d in doc_list],
                "doc_ids": [d.doc_id for d in doc_list],
                "principle_count": len([d for d in doc_list if d.doc_type == "weekly"]),
                "experience_count": len([d for d in doc_list if d.doc_type == "daily"])
            }
        }

    def chat(self, query: str, raw_top_k=RC.DEFAULT_RAW_TOP_K, final_top_k=RC.DEFAULT_FINAL_TOP_K, memory_context: str = "", chat_history: str = "", guided_reasons: str = "") -> Dict[str, Any]:
        """兼容入口：检索 + 生成（retrieve → generate）。

        阶段 4-A 起，direct 咨询改为路由 Agent 先按需调 retrieve_knowledge_tool、
        再由 psychological_consult_tool 调 generate；本方法保留给需要一锅端的场景。
        """
        doc_list = self.retrieve(query, raw_top_k, final_top_k)
        return self.generate(
            query, doc_list,
            memory_context=memory_context,
            chat_history=chat_history,
            guided_reasons=guided_reasons,
        )