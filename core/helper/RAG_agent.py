from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from config.model_config import GLOBAL_MODEL, get_langchain_llm
from config.prompt_config import RAG_system_prompt, RAG_human_prompt

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
        retriever,
        chat_model: BaseChatModel | None = None,
    ):
        self.retriever = retriever
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
                "guided_reasons": lambda inputs: inputs.get("guided_reasons", "暂无已完成推理")
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

    def chat(self, query: str, raw_top_k=6, final_top_k=3, memory_context: str = "", chat_history: str = "", guided_reasons: str = "") -> Dict[str, Any]:
        problem, situation = self._split_query(query)
        # 完整检索拿到重排后的全部文档（仅用问题描述，避免情境稀释召回）
        doc_list = self.retriever.retrieve(problem, raw_top_k, final_top_k)
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
            guided_reasons=reason_ctx
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