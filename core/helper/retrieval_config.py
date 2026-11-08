"""检索链路的「全局默认参数」唯一来源。

调优过程、消融数据与结论见 docs/rag_optimization_report.md。这里只放**结论**：
生产链路（preprocess / api.tool / Retriever / RetrievalPipeline / 调试 API）都从这里取默认值，
避免同一组参数在五六个文件里各写一遍而漂移。

分三类：
1. 索引侧（建库时生效，改它必须重建 BM25 索引 / 向量库）
2. 查询侧（每次检索生效，可通过调试 API 覆盖）
3. 融合 / 重排侧

一句话总结调优结论（31 条 query × 31 篇文档的 rag_optimize 数据集）：
    「富索引 BM25 + 归一化加权 RRF（k=3）+ 交叉编码器分数与融合排名分混合（alpha=0.3）」
把 loose@3 / strict@3 / MRR 同时推到 1.000，且没有任何 hard negative 排在有效文档之前。
"""
from __future__ import annotations

# ===================== 1. 索引侧（需要重建索引才生效） =====================

# BM25 富索引字段权重（相对值；实现上用「词项重复次数 × WEIGHT_SCALE」表达，见 BM25TagIndexer._repeat）。
# 设计动机：v1 索引只放 LLM 抽取的 topics(×3)+keywords(×1)，BM25 的 IDF/词频/长度归一化
# 全都作用在「构造产物」上，与原文的词频分布脱钩。富索引把标题 / 摘要 / 周记三段 / 正文
# 一起纳入，让词频差异与长度归一化重新作用在真实文本上。
BM25_FIELD_WEIGHTS = {
    "topic": 3.0,      # 主题标签：语义聚合强 → 高权重
    "keyword": 2.0,    # LLM 关键词：外部构造中最具特异性
    "title": 3.0,      # 标题：全文最凝练的主题表述
    "summary": 2.0,    # 摘要：凝练但含较多泛化词
    "problem": 2.0,    # 周记 problem：用户自己写的问题定义，与口语化提问同构
    "solution": 2.0,   # 周记 solution：真正「有效」的答案所在
    "analysis": 1.0,   # 周记 analysis：铺垫最长、区分度最低
    "content": 1.0,    # 正文：提供真实词频与真实文档长度
}
# 长度归一化强度与词频饱和参数。周记天然比日记长得多但更具代表性，
# b 从 sklearn 默认 0.75 降到 0.4 可避免长文被过度惩罚（实测 b=0.4 优于 0.75）。
BM25_K1 = 1.5
BM25_B = 0.4

# dense 文档编码规格（见 core/helper/retrieval_text.dense_doc_text）
# problem_solution：周记取「标题+摘要+problem+solution」，日记取「标题+摘要+正文前段」
DENSE_DOC_VARIANT = "problem_solution"

# ===================== 2. 查询侧 =====================

# BM25 查询词项权重（相对值，整数重复实现；BM25 分数对整体缩放不变，所以只用相对比例）。
# 实测：把 LLM 扩展的泛化关键词降到原话的一半权重（2:1:2）比等权（1:1:1）覆盖率更高；
# distinctive_terms 与原文分词高度重叠，加权后反而引入噪声，因此默认权重为 0
# （字段仍保留在 optimizer 输出与调试面板中，便于按需启用/排查）。
BM25_QUERY_WEIGHTS = {
    "query": 2.0,        # 用户原话分词 —— 最具区分度
    "distinctive": 0.0,  # 从原话逐字抽取的高区分度片段（与 query 重叠，默认不额外加权）
    "search_query": 0.0,  # LLM 改写问句（默认不进 BM25 词袋，由 dense 承担）
    "keywords": 1.0,     # LLM 关键词（可能有泛化词，半权重）
    "topics": 2.0,       # 英文主题标签（区分度低但语义稳定）
}

# dense 查询多向量混合权重：把「原始提问」与「改写问句」分别编码后加权平均再归一化。
# 实测 1 : 0.5 优于字符串拼接（v1 的 `search_query + query` 无分隔符且不可调）。
# 说明：HyDE 假设文档**不加进主查询向量**——实测会稀释原始意图（见报告消融表）；
# 它只作为可选的第 3 条召回链路（RetrievalPipeline.run(use_hyde=True)）。
DENSE_QUERY_WEIGHTS = {
    "query": 1.0,
    "search_query": 0.5,
    "hyde_experience": 0.0,
    "hyde_principle": 0.0,
}

# ===================== 3. 融合 / 重排侧 =====================

DEFAULT_RAW_TOP_K = 15        # 每路召回候选数（v1 为 6；31 篇库下 15 能覆盖双路并集）
DEFAULT_FINAL_TOP_K = 3
DEFAULT_RRF_K = 3             # v1 为 60：k 太大时 1/(pos+k) 几乎与排名无关，融合退化为无序并集
DEFAULT_W_DENSE = 1.0
DEFAULT_W_BM25 = 1.0
DEFAULT_SCORE_THRESHOLD = 0.0  # 0.0 = 不做硬阈值过滤（重排默认走 blend 模式，见下）
DEFAULT_RERANK_POOL = 10       # 先按融合排名截断到前 N 再送 cross-encoder；0 = 不截断
DEFAULT_USE_HYDE = False       # HyDE 独立链路（实测对本库无净增益，且多一次 LLM 调用）

# 重排使用方式：
#   "blend" —— 最终分 = 融合排名归一化分 + alpha × cross-encoder 概率（默认）
#              交叉编码器只用于「在融合排名附近做精修」，不再单独决定一切；
#   "filter"—— 保持融合排名，仅用 cross-encoder 做置信闸门；
#   "sort"  —— v1 行为，完全由 cross-encoder 决定排序与阈值过滤。
DEFAULT_RERANK_MODE = "blend"
DEFAULT_BLEND_ALPHA = 0.3

# cross-encoder 文档侧输入规格（legacy/with_kw/problem_solution/full，见 retrieval_text）
# 与传给 cross-encoder 的查询文本（raw=原始提问 / search=改写问句 / both）
RERANK_INPUT_VARIANT = "legacy"
RERANK_QUERY = "raw"

# 调试 API 的参数区间（api/retrieval_debug.py 复用）
RAW_TOP_K_RANGE = (1, 50)
FINAL_TOP_K_RANGE = (1, 50)
RRF_K_RANGE = (1, 1000)
SCORE_THRESHOLD_RANGE = (0.0, 1.0)
W_RANGE = (0.0, 10.0)
RERANK_POOL_RANGE = (0, 50)
BLEND_ALPHA_RANGE = (0.0, 5.0)
RERANK_MODES = ("blend", "filter", "sort")

# ===================== 4. 证据充分性与 CRAG 补救（阶段 4-C） =====================
# 证据分级口径：只看「最终证据里最高的 cross-encoder 概率」（0~1，sigmoid 输出）。
# 注意：CE 概率对「查询措辞」高度敏感 —— 同一篇文档，用户原话可得 0.75，
# LLM 改写后的短句只有 0.195，甚至 0.078。因此该阈值只能当「基本无关」的地板用，
# 不能当质量线。实测：相关改写句 0.195，离题查询 0.0045 / 0.0115。
# 取 0.05：只拦「明显跑偏」（低于 5%），不会把措辞不同但命中的证据误判为缺失
# （误判代价是白跑一次补救并提前关掉本轮检索）。
EVIDENCE_MIN_TOP_SCORE = 0.05

# 方法类提问关键词：命中时若证据里 0 条周记（心理原则/调节方案），判为 no_principle。
# 只作为「补救触发信号」，不作为最终回复的拒绝理由。
EVIDENCE_METHOD_HINTS = (
    "怎么", "如何", "怎么办", "方法", "建议", "该不该",
    "练习", "改善", "停止", "摆脱", "应对", "理解",
)

# 分解查询的硬边界：太短不分解；单条子查询不超过该长度（分解产物要能独立检索）
DECOMPOSE_MIN_CHARS = 12
DECOMPOSE_MAX_SUB_CHARS = 40

# 一次补救最多用 3 条查询（含原查询）；补救只执行一轮，绝不递归/循环
REMEDIATION_MAX_QUERIES = 3
# 补救时扩大候选池：raw_top_k 与 rerank_pool 同时放大，但 final_top_k 不变
# （只改变「候选能不能进重排池」，不改变交给 LLM 的证据条数，避免上下文膨胀）
REMEDIATION_EXPAND_TOP_K = 25
REMEDIATION_EXPAND_RERANK_POOL = 20

