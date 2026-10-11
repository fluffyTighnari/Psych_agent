"""单次咨询过程：
初始化EmbeddingModel、VectorDB、BM25TagIndexer、LLM、PromptOptimizer、KnowledgeLoader、Reranker、Retriever、PsychRAGAgent
agent.chat(prompt) -> retriever.retrieve
                      (prompt_optimizer.optimize_prompt -> |retrieve_summary| -> rrf_fuse -> knowledge_loader.load_knowledge -> reranker.rerank_documents)
                                                           |retrieve_topics |
"""
from core.agent import agent_service_entry
# prompt = "非常焦虑，不知道自己喜欢什么，也不知道自己能做什么，觉得自己总是随波逐流，想要坚定自我却又发现无能为力怎么办"
# prompt = "在人际关系中有很强的焦虑型依恋怎么办，突然到来的一点冷漠就可能让我不安几个小时，直到对方再次以热情拥抱我。但这本身就应该是我自己的人生课题，我并不是为了别人而活"
# prompt = "如何解决后发性共情：因为想要在交往中体现的更加务实与专注，所以聚焦问题而有些不近人情，但在这之后又因为自己可能做了或者说了一些让别人感到不舒服的事或者话，独自深深的内耗和后悔"
# prompt = "其实这里的共情已经是我刻意调整后的结果，因为我之前总是陷入无效共情，但是我认为解决问题的方式更健康。但是这样一来，我似乎走向了另一个极端，我觉得我需要一些具体方法来保持二者的平衡"

def chat_loop():
    while True:
        user_text = input("用户输入：")
        if user_text in ("quit", "exit"):
            break
        res = agent_service_entry(user_text)
        print(f"\n助手回复：{res['reply']}")

chat_loop()