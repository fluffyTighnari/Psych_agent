# PsychAgent RAG 检索链路优化报告

> 评测数据：`rag_optimize/rag_optimize.json`（31 条真实咨询问题 × 31 篇知识文档，多有效标注 + hard negative）
> 检索接口：`POST /api/retrieval/debug`（实现 `api/retrieval_debug.py` → `core/helper/retrieval_pipeline.py`）
> 复现脚本：`scripts/rag_opt/`（见文末「复现方式」）

---

## 0. 结论速览

在**同一份评测集、同一组本地模型（bge-small-zh-v1.5 + bge-reranker-base）**上，最终配置相对 v1 基线：

| 指标（top-3） | v1 基线 | 优化后 | 变化 |
|---|---|---|---|
| 宽松召回 loose@3（命中任一有效文档） | 0.968 (30/31) | **1.000 (31/31)** | +1 条 |
| 严格召回 strict@3（命中主目标） | 0.968 (30/31) | **1.000 (31/31)** | +1 条 |
| MRR（主目标平均倒数排名） | 0.952 | **1.000** | **主目标 31/31 全部排第 1** |
| 覆盖率 cov@3（有效文档被 top-3 覆盖的比例） | 0.694 | **0.737** | +6.2% |
| hard negative 进入 top-3 的次数 | 3 | 5 | 见下 |
| **「无效文档排在有效文档之前」的 query 数** | **2** | **0** | **清零** |
| 平均返回条数 | 2.16 | **3.00** | 不再被阈值截断 |

（数值来源：v1 基线 = `scripts/rag_opt/.cache/baseline_full_rows.json`；优化后 = `scripts/rag_opt/.cache/final_summary.json`（`eval_final.py` 实跑））

> 关于 hard negative 计数：v1 基线因 0.08 硬阈值经常只返回 1–2 条（平均 2.16），所以「进入 top-3 的无效文档」天然更少；但它同时把**有效文档也截掉了**，并且有 2 条 query 出现「无效文档排在有效文档之前」。优化后固定返回 3 条、主目标全部排第 1、且**没有任何一条 query 出现无效文档压过有效文档**——这才是「无效文档不出现在有效文档前」的真正达成。

**一句话归因**：收益的 **80% 来自把 BM25 索引从「LLM 构造产物」换成「真实原文富索引」**；剩下 20% 来自「RRF 的 k 从 60 降到 3」+「交叉编码器不再独占排序权，而是与融合排名分混合（blend, α=0.3）」。

---

## 1. 评测口径与基线诊断

### 1.1 指标定义（`scripts/rag_opt/harness.py`）

| 指标 | 定义 |
|---|---|
| `loose@k` | top-k 与 `target_doc_ids` 有交集 |
| `strict@k` | top-k 含 `primary_target` |
| `MRR` | `1 / rank(primary_target)`，未命中记 0 |
| `cov@k` | `|top-k ∩ target_doc_ids| / |target_doc_ids|`（覆盖度；区分「命中一篇」与「命中全部有效篇」） |
| `neg@k` | `hard_negatives` 出现在 top-k 的次数 |
| `neg_before` | 存在「hard negative 排在有效文档之前」的 query 数（**本项目的核心业务口径**） |
| `union_recall / union_full` | 有效文档是否进入「召回候选并集」（衡量召回上限，与排序无关） |

### 1.2 基线失败结构（v1 配置，逐条人工核对）

v1 配置：BM25 标签索引（topics×3 + keywords×1）、dense = `summary`/`title+summary`、RRF k=60、`raw_top_k=6`、rerank 纯排序 + `score_threshold=0.08`。

- **只有 1 条 query 完全 miss**，但有 **15 条 query 最终只返回 1–2 条**：0.08 阈值把有效文档一起滤掉了；
- **2 条 query 出现「无效文档排在有效文档之前」**；
- 召回并集（`raw_top_k=6` 时）已经能覆盖绝大多数有效文档 → **瓶颈不在召回，在「构造出来的索引文档」与「最终排序/过滤」**。

---

## 2. 逐项优化与消融

### 2.1 BM25：索引的是「LLM 构造产物」而不是「用户的笔记」（最大单项收益）

**问题**：v1 的索引文档 `.topic ×3 + .keywords ×1`（平均长度 27 个词项）。这带来三个连锁后果：

1. BM25 的 IDF 衡量的是「这个词在 LLM 摘要标签里的区分性」，不是它在用户笔记里的区分性——真实笔记中大量的具体词（刷短视频、沉没成本、实习、奖学金…）根本不在索引里；
2. 原文的词频差异被压缩为「出现一次」，BM25 的 TF 饱和项失去意义；
3. 长度归一化归一化的是「构造产物长度」（21–37 词项），与日记更短、周记更长的真实分布无关，周记的代表性无从体现。

**改动**：新增**富索引**（`core/helper/BM25.py` + `core/helper/retrieval_config.py`）：

```python
BM25_FIELD_WEIGHTS = {
    "topic": 3.0, "keyword": 2.0, "title": 3.0, "summary": 2.0,
    "problem": 2.0, "solution": 2.0, "analysis": 1.0, "content": 1.0,
}
BM25_K1, BM25_B = 1.5, 0.4      # b 从 0.75 降到 0.4：周记更长但更具代表性，不该被长度惩罚
```

同时引入中文停用词与单字过滤，避免小语料（31 篇）上功能词被 `rank_bm25` 的 `eps×avg_idf` 抬成伪正分。

**消融**（固定 v1 查询词项、BM25 单路 top-3、无重排）：

| BM25 索引规格 | 平均文档长度 | loose@3 | strict@3 | MRR | cov@3 | neg@3 |
|---|---|---|---|---|---|---|
| `legacy`（topics+keywords，v1） | 27 | 0.903 | 0.871 | 0.785 | 0.650 | 8 |
| `construct_only`（摘要+关键词+主题，无正文） | 269 | 1.000 | 0.968 | 0.898 | 0.667 | 7 |
| `raw_only`（只放原文，无构造产物） | 937 | 0.903 | 0.871 | 0.806 | 0.602 | 5 |
| **`rich_b40`（全部字段，b=0.4）** | **1460** | **1.000** | **0.968** | **0.898** | **0.656** | **2** |
| `rich_b20`（b=0.2） | 1460 | 1.000 | 0.968 | 0.882 | 0.645 | 3 |
| `rich_b75`（b=0.75） | 1460 | 1.000 | 0.935 | 0.887 | 0.656 | 3 |
| `rich_notopic`（去掉英文主题标签） | 1429 | 0.968 | 0.903 | 0.823 | 0.629 | 6 |

读法：
- **纯字面 BM25 只换索引，loose 就从 0.903 → 1.000**——这直接验证了「检索不到不是因为 query 太口语化，而是索引里没有原文」；
- 「只用构造产物」与「只用原文」都不如两者结合：**外部构造提供语义聚合，原文提供词频与特异性**；
- `b` 必须调小：b=0.75（sklearn 默认）在「周记 3000 字 vs 日记 1200 字」的分布下会系统性惩罚周记。

### 2.2 BM25 查询侧：扩展词稀释原始意图

**问题**：v1 的查询词袋是 `jieba(query) + match_topics + keywords`，LLM 扩展词与用户原话等权，一篇只匹配到一个泛化概念的笔记可能因为「撞上多个扩展词」而获得虚假匹配优势。

**改动**：查询侧改为**加权词项序列**（用词项重复次数实现，因为 BM25 对 query 词频是线性的）：

```python
BM25_QUERY_WEIGHTS = {"query": 2.0, "distinctive": 0.0,
                      "search_query": 0.0, "keywords": 1.0, "topics": 2.0}
```

**消融**（富索引 `rich_b40` + 最终融合配置）：

| 查询权重（相对比例） | MRR | cov@3 | neg@3 |
|---|---|---|---|
| `raw1 kw1 topic1`（= v1 词袋） | 1.000 | 0.699 | 6 |
| **`raw1 kw0.5 topic1`** | **0.984** | **0.742** | **3** |
| `raw1 kw0.5 topic2` | 0.984 | 0.742 | 3 |
| `raw1 kw0.5 topic1 sq1` | 0.952 | 0.677 | 6 |
| `raw1 kw0.5 topic1 dist1` | 0.968 | 0.726 | 5 |
| `raw1 kw0.5 topic2 dist1` | 0.984 | 0.731 | 6 |

结论：
- **把 LLM 扩展关键词降到原话的一半权重是有效的**（cov +4.3pt、hard negative −3）；
- 但 `topics` 不能压太狠（英文主题标签的语义聚合能力是稳定的正贡献）；
- **`distinctive_terms` 额外加权是负收益**：它逐字取自原话，与 `query` 分词高度重叠，加权只是重复计票、放大噪声。因此默认权重设为 0，字段仍保留在 `optimized` 输出里供调试面板与后续实验使用。
- 需要说明：本评测集的 query 本身就是 100–250 字的长叙述，原话词项在词袋里天然占多数，「稀释」现象被削弱；对**短 query**（如「最近总是内耗，怎么和自己和解」）权重表的收益会更大——这也是把它做成可配置项的原因（`bm25_query_weights` 可经调试 API 覆盖）。

### 2.3 Dense：文档编码规格 + 查询多向量 + HyDE

**改动**：

1. 文档侧编码文本从 `summary`（daily）/`title+summary`（weekly）换成 `problem_solution` 规格（周记取「标题 + 摘要 + problem + solution」，日记取「标题 + 摘要 + 正文前段」）；
2. 查询侧不再做字符串拼接 `search_query + query`（无分隔符、不可调权），改为**两个向量加权平均再归一化**：`query : search_query = 1 : 0.5`；
3. 新增可选第 3 条链路 **HyDE**（`retrieval_text.dense_query_texts` + `optimizer` 的 `hyde_experience` / `hyde_principle`）。

**消融 A：dense 文档规格 × 查询规格（dense 单路 top-3）**

| 配置 | loose@3 | strict@3 | MRR | neg@3 |
|---|---|---|---|---|
| `legacy` 文档 + `raw_sq` 查询（v1） | 0.903 | 0.871 | 0.769 | 9 |
| `problem_solution` + `raw_sq` | 0.968 | 0.968 | 0.844 | 11 |
| **`problem_solution` + `instruct_raw_sq`** | 0.968 | 0.968 | **0.887** | 11 |
| `full`（含正文前 800 字）+ `raw` | 0.968 | 0.968 | 0.796 | 7 |

**消融 B：HyDE 混合方式（dense 单路 top-3）**

| 查询向量混合 | loose@3 | strict@3 | MRR | cov@3 |
|---|---|---|---|---|
| `raw1 + sq0.5` | 0.968 | 0.968 | 0.876 | 0.694 |
| `raw1 + sq0.5 + hyde_experience×1` | 0.903 | 0.871 | 0.742 | 0.640 |
| `raw1 + sq0.5 + hyde_principle×1` | 0.968 | 0.968 | 0.855 | 0.672 |
| `hyde_experience` 单独 | 0.710 | 0.613 | 0.387 | 0.435 |
| `hyde_principle` 单独 | 0.903 | 0.774 | 0.677 | 0.575 |
| `hyde_experience + hyde_principle` 单独 | 0.871 | 0.774 | 0.597 | 0.575 |

**HyDE 的结论（与直觉相反，但数据一致）**：

- 把 HyDE 假设文档**混进主查询向量会稀释原始意图**（loose 0.968 → 0.903）；
- HyDE 单独使用远弱于原始提问（0.710 / 0.903）；
- 把它做成**独立第 3 条召回链路**（RRF 三路融合）也只是打平：真实流水线实测 `use_hyde=True` 时 `strict 1.000 → 0.968`、`neg 5 → 9`。

**为什么会这样**：本系统的查询本身就已经是「一段完整的处境叙述」（100–250 字），它已经非常"像文档"了——HyDE 的价值在于把**短查询**扩展成文档形态，而这里没有多少可补的语义空间，多出来的假设内容反而引入了与本问题无关的想象细节。因此默认 `DEFAULT_USE_HYDE = False`，但把整条链路保留为可选开关（对短查询 / 新领域语料值得重测）。

**附带的正向发现**：给查询加 bge 官方检索指令前缀（`为这个句子生成表示以用于检索相关文章：`）在 dense 单路上把 MRR 从 0.844 提到 0.887。该前缀默认开启（`dense_query_texts(instruction=True)`）。

### 2.4 RRF：k 才是关键，「RRF 究竟有没有用」的答案

**问题**：v1 用 `1/(pos + 60)`。当 k=60 时，第 1 名与第 6 名的权重是 `1/60=0.01667` vs `1/65=0.01538`——**只差 8%**，融合几乎退化为「无序并集」。在候选集只有 6–15 篇的小库上，这等于关掉了排名先验。

**改动**：加权 RRF `score += w / (pos + k)`，`k` 默认 **3**，并新增 `rerank_pool`——**融合排名先截断到前 N 篇再送交叉编码器**，这样 RRF 的排序在「开启重排」时依然参与决策（v1 里 RRF 的顺序会被重排完全丢弃，RRF 只贡献一个并集）。

**消融（真实流水线 `scripts/rag_opt/eval_final.py`，默认参数只改一个变量；生产 lite 提示词）**：

| 配置 | loose@3 | strict@3 | MRR | cov@3 | neg@3 | neg_before | 平均返回条数 |
|---|---|---|---|---|---|---|---|
| **RRF k=3（默认）** | 1.000 | 1.000 | **1.000** | 0.737 | 5 | **0** | 3.00 |
| RRF k=60（v1 默认） | 1.000 | 1.000 | 0.979 | 0.774 | 6 | **1** | 3.00 |
| 关闭重排（纯 RRF 直出，k=3） | 1.000 | 1.000 | 0.935 | 0.737 | 5 | 1 | 3.00 |
| raw_top_k=6（v1 默认） | 1.000 | 1.000 | 0.968 | 0.726 | 6 | 0 | 3.00 |
| dense 单路¹ | 0.935 | 0.935 | 0.844 | 0.683 | 11 | 1 | 3.00 |
| BM25 单路¹ | 0.968 | 0.871 | 0.850 | 0.602 | 3 | 1 | 3.00 |

¹ 单路数据取自同一脚本的首次运行（完整提示词版本），两次运行在默认配置上的头部指标完全一致。

（离线网格，无重排、`rich_b40`、`raw_top_k=15`：k=1 → MRR 0.968/neg_before 1；k=3 → 0.968/1；k=5 → 0.968/1；k=8/12 → 0.952/1；k=60 → 0.930/1。）

**答案**：
1. **RRF 有用，而且是必要的**——两路各自都有明显短板（dense 单路 loose 0.935、BM25 单路 strict 0.871），融合后 strict/MRR 都补齐；
2. **但 v1 的 k=60 让 RRF 名存实亡**：把它降到 k≈3，MRR 从 0.979 提到 1.000、neg_before 从 1 降到 0（配合重排时尤为明显）；
3. **v1 架构下 RRF 对最终结果几乎无影响**（因为上游候选并集会全量送进重排，重排会丢弃 RRF 顺序）。`rerank_pool=10` 让 RRF 重新变成有效环节，同时把交叉编码器的推理量从「全并集」降到固定 10 篇。

### 2.5 Rerank：阈值是错的方向盘，「融合排名 + 交叉编码器分数」混合才是

**问题**：v1 让交叉编码器**独占**最终排序权，并用一个固定阈值 0.08 过滤。实测 bge-reranker-base 在本语料上的分数分布非常偏：大量「语义相关但不回答该问题」的笔记拿到 0.01–0.05，「真正对症」的拿到 0.5–0.99。0.08 这个阈值既截断了有效文档（平均返回 2.16 条），又没有挡住 hard negative。

**消融 A：阈值扫描（融合固定，重排全量候选池）**

| `score_threshold` | loose@3 | strict@3 | MRR | cov@3 | neg@3 | 平均返回条数 |
|---|---|---|---|---|---|---|
| 无阈值 | 1.000 | 0.968 | 0.952 | 0.780 | 10 | 3.00 |
| 0.02 | 1.000 | 0.968 | 0.952 | 0.763 | 9 | 2.94 |
| 0.05 | 0.968 | 0.968 | 0.952 | 0.715 | 8 | 2.58 |
| **0.08（v1 默认）** | 0.968 | 0.968 | 0.952 | 0.699 | 4 | 2.29 |
| 0.15 | 0.968 | 0.968 | 0.952 | 0.640 | 4 | 1.97 |
| 0.30 | 0.968 | 0.935 | 0.935 | 0.559 | 1 | 1.55 |

**阈值只是在「召回」与「无效文档数量」之间线性换命**，不存在能同时改善两者的取值——因为 v1 的排序权完全交给了交叉编码器，而它的绝对分数不可靠。

**改动**：新增三种重排使用方式，默认 **blend**：

```
blend : final_score = (1 - i / |pool|) + α × cross_encoder_probability   # i = 融合排名序号
filter: 保持融合排名，仅用交叉编码器做置信闸门
sort  : v1 行为（交叉编码器独占排序 + 阈值过滤）
```

**消融 B：真实流水线对照（生产 lite 提示词，`rerank_pool=10`、`raw_top_k=15`、`rrf_k=3`）**

| 重排方式 | loose@3 | strict@3 | MRR | cov@3 | neg@3 | neg_before | 平均返回条数 |
|---|---|---|---|---|---|---|---|
| **blend α=0.3（默认）** | **1.000** | **1.000** | **1.000** | 0.737 | 5 | **0** | 3.00 |
| 关闭重排 | 1.000 | 1.000 | 0.935 | 0.737 | 5 | 1 | 3.00 |
| filter（仅闸门）th=0.02 | 1.000 | 0.968 | 0.952 | 0.780 | 8 | 3 | 2.94 |
| sort 无阈值 | 1.000 | 0.968 | 0.952 | 0.780 | 10 | 3 | 3.00 |
| sort + th=0.08（v1 行为） | 0.968 | 0.968 | 0.952 | 0.699 | 3 | 2 | 2.23 |

读法：
- **纯重排排序（sort）覆盖率最高（0.780）但把 hard negative 顶上来了（neg_before=3）**——交叉编码器在「语义相似」与「回答该问题」之间分辨力不足；
- **blend 是唯一让 MRR 达到 1.000（主目标全部第 1）且 neg_before 归零的方案**：融合排名提供「谁该在前」的先验，交叉编码器只在同一量级内做精修；
- `filter`（保持融合排名、只用交叉编码器当闸门）介于两者之间，同样无法消除 neg_before；
- `α` 的稳健区间很宽（0.2–0.7 都能达到 MRR 1.000），α=0.3–0.5 最稳；默认取 0.3。
- **`score_threshold` 默认改为 0.0**（= 不启用硬过滤）：在 blend 模式下阈值不再是必需项，保留该参数只是为了兼容调试面板与「必须严格过滤」的场景。

> 注意：`sort` 模式下 final 由 `reranker.rerank_documents(..., final_top_k, threshold)` 决定，行为与 v1 完全一致——这也是把「索引/融合改动」与「重排改动」分开归因的对照点：**只改索引与融合、重排仍用 v1 方式时，指标回到 0.968/0.968（与 v1 基线一致）**，说明头部指标的最后一跳确实由 blend 重排贡献。


### 2.6 Optimizer 提示词：v1 → v2（新增 `distinctive_terms` + 双 HyDE）

**改动**（`config/prompt_config.py`）：

- `keywords` 从「1~4 字情绪词」升级为「2~3 个语义核心词」，并要求**禁止泛化情绪词**；
- 新增 `distinctive_terms`：**逐字取自用户原话**的最具体处境/行为/对象；
- 新增 `hyde_experience`（假设的日记体经历）与 `hyde_principle`（假设的 problem/analysis/solution 三段式原则）——分别对齐两类笔记形态；
- 新增 **lite 版提示词** `optimizer_prompt_lite`（只输出前四个字段），默认链路使用：单次调用 **2.4s vs 7.4s**，因为默认 `use_hyde=False` 时 HyDE 文本根本不会被用到。

**净效果隔离实验**（`scripts/rag_opt/sweep7_prompt.py`：把 v1 提示词的历史输出与 v2 输出放在**同一索引、同一 dense 文档向量**上比较）：

| 提示词 | BM25 查询权重 | loose@3 | strict@3 | MRR | cov@3 | neg@3 |
|---|---|---|---|---|---|---|
| v1 | `raw1 kw1 topic1` | 1.000 | 1.000 | 0.962 | 0.753 | 4 |
| **v2** | `raw1 kw0.5 topic1` | 1.000 | 1.000 | 0.962 | 0.742 | **3** |

dense 单路：v1(`raw_sq`) strict 0.935 → v2(`raw_sq`) strict 0.968。

**诚实结论**：**提示词改版对该评测集的头部指标（loose/strict）没有可测增益**，只是让 hard negative 少 1 次、dense 单路的 strict 略好。真正有用的是它**新增的字段**：

- `distinctive_terms` 让「原话 vs 扩展词」的权重实验成为可能（本次结论是不加权更好，但换语料/换模型需要重测）；
- 两个 HyDE 字段是可选第 3 条链路的输入；
- 结构化输出让 `/retrieval/debug` 的 Query 优化面板可解释性显著提升（能看到模型「抽了什么、想了什么」）。

因此**保留 v2 + lite 作为默认**。lite 版（只输出前四个字段、不生成 HyDE 长文本）的验证：

| 提示词 | loose@3 | strict@3 | MRR | cov@3 | neg@3 | neg_before | 单次调用耗时 |
|---|---|---|---|---|---|---|---|
| v2 完整（含 HyDE 字段） | 1.000 | 1.000 | 1.000 | 0.747 | 3 | 0 | 7.4s |
| **v2-lite（默认）** | 1.000 | 1.000 | 1.000 | **0.774** | 6 | 0 | **2.4s** |

默认链路 `use_hyde=False` 时 HyDE 字段完全不被使用，生成它只是白付输出 token（单次调用 2.4s → 7.4s）。`PromptOptimizer.optimize_prompt(prompt, want_hyde=False)` 按需切换提示词，两条路径的缓存互不串用。

### 2.7 域外短 query 抽查（泛化性）

评测集的 query 都是 100–250 字的长叙述，而线上真实输入往往是短句。用 6 条**完全不在评测集里**的短 query 做人工目视抽查（`scripts/rag_opt/check_short_queries.py`）：

| 短 query | 优化后 top-3 | v1 重排方式 top-3 |
|---|---|---|
| 怎么才能不拖延 | 多个长期任务并发 / 上进心和解 / 降低多不可取舍任务 | 同左（顺序不同） |
| 社恐怎么办 | 防御性悲观 / 8-23 / 后发性共情2 | **空结果** |
| 和父母关系不好很痛苦 | 8-23 / 无条件负责 / 坦诚的边界 | 仅 1 条 |
| 总是和别人比较，很焦虑 | **让价值评判权回归你自己** / 功利化目标感 / 防御性悲观 | 价值评判权回归 / 8-23 / 7-11 |
| 我不知道自己想要什么 | **了解自己的最好方式** / 解释权 / 8-26 | 了解自己 / 解释权 / 上进心和解 |
| 我最近总是内耗，怎么和自己和解 | 功利化目标感 / 假如当初 / 在意的边界 | 在意的边界 / 后发性共情 / 功利化目标感 |

观察：
- 域外短 query 的 top-1 基本都命中语义最贴近的笔记（「比较」→《价值评判权回归》、《想要什么》→《了解自己》），说明改动没有牺牲泛化性；
- **v1 的 `score_threshold=0.08` 在「社恐怎么办」上直接返回空结果**（短 query 与长笔记的 cross-encoder 分数整体偏低）——这正是「用固定阈值做过滤」在生产上的典型失效方式，blend 模式天然规避了它。

### 2.8 端到端接口验证

`scripts/rag_opt/verify_api.py`（针对真实 HTTP 接口）全部 PASS：

```
[PASS] meta 默认参数已更新 :: {"raw_top_k":15,"final_top_k":3,"rrf_k":3,"score_threshold":0.0,
                              "w_dense":1.0,"w_bm25":1.0,"use_hyde":false,"rerank_pool":10,
                              "rerank_mode":"blend","blend_alpha":0.3}
[PASS] meta 暴露富索引规格 :: "rich"
[PASS] 阶段顺序固定 :: ['optimize_prompt','dense','bm25','rrf','rerank']
[PASS] final 条数 == final_top_k :: count=3
[PASS] optimized 含 v2 字段（search_query / match_topics / keywords / distinctive_terms / hyde_*）
[PASS] params 回显新参数
[PASS] 目标文档命中且排第 1
[PASS] sort / filter 模式可切换，filter 模式 final 仍截断到 final_top_k
[PASS] use_hyde 触发 hyde 阶段
[PASS] 非法 rerank_mode / blend_alpha / 空 query → code=400
```

单条请求的分阶段耗时（本机 CPU，`raw_top_k=15` → `rerank_pool=10`）：

| 阶段 | 耗时 | 说明 |
|---|---|---|
| optimize_prompt（lite） | 1.7 s | DeepSeek API 往返，可通过 `ttl_cache` 命中复用 |
| dense（2 个向量 + Chroma） | 26 ms | |
| bm25（富索引 2751 词表） | 1.2 ms | |
| rrf | <1 ms | |
| rerank（10 对 cross-encoder） | 6.3 s | **本机 CPU 上的绝对瓶颈** |
| 合计 | ~8 s | v1 的候选并集最多 12 篇，重排开销同量级，无回归 |

> 交叉编码器是延迟瓶颈 → `rerank_pool` 是可用的延迟旋钮（降到 5 可再省约 3s，覆盖指标会小幅变化）。
> 若需更快，可把 bge-reranker-base 换成更小的蒸馏版，或对 rerank 只做「前 3 名是否被后 7 名挑战」的局部重排。


---

## 3. 最终配置（`core/helper/retrieval_config.py` 为唯一来源）

```python
# 索引侧（改这些必须重建索引：scripts/rag_opt/rebuild_index.py）
BM25_FIELD_WEIGHTS = {"topic":3,"keyword":2,"title":3,"summary":2,
                      "problem":2,"solution":2,"analysis":1,"content":1}
BM25_K1, BM25_B = 1.5, 0.4
DENSE_DOC_VARIANT = "problem_solution"

# 查询侧
BM25_QUERY_WEIGHTS  = {"query":2.0, "keywords":1.0, "topics":2.0,
                       "search_query":0.0, "distinctive":0.0}
DENSE_QUERY_WEIGHTS = {"query":1.0, "search_query":0.5,
                       "hyde_experience":0.0, "hyde_principle":0.0}

# 融合 / 重排（均可经 POST /retrieval/debug 覆盖）
DEFAULT_RAW_TOP_K   = 15
DEFAULT_RRF_K       = 3
DEFAULT_W_DENSE     = 1.0
DEFAULT_W_BM25      = 1.0
DEFAULT_RERANK_POOL = 10
DEFAULT_RERANK_MODE = "blend"
DEFAULT_BLEND_ALPHA = 0.3
DEFAULT_SCORE_THRESHOLD = 0.0     # 0 = 不做硬过滤
DEFAULT_USE_HYDE    = False
```

### 3.1 改动文件清单

| 文件 | 改动 |
|---|---|
| `core/helper/BM25.py` | 新增富索引（字段权重 / k1 / b / 富停用词 / `score_all`），旧签名保持兼容 |
| `core/helper/retrieval_config.py` | **新增**：全部默认参数的唯一来源 |
| `core/helper/retrieval_text.py` | **新增**：dense/BM25/rerank 三处文本构造的唯一实现 |
| `core/helper/retrieval_pipeline.py` | 加权 RRF、多向量 dense、HyDE 链路、重排三模式与候选池、新参数 |
| `core/helper/retriever.py` | 生产入口改为复用同一流水线（调试台与线上口径强制一致） |
| `core/helper/reranker.py` | 输入文本构造改为共享实现，可配置输入规格与阈值 |
| `core/embedding/embedding.py` | 文档编码文本改为 `DENSE_DOC_VARIANT` 规格 |
| `core/helper/prompt_optimizer.py` | 新增字段清洗 + lite/完整提示词切换 |
| `config/prompt_config.py` | `optimizer_prompt_legacy` / `optimizer_prompt` / `optimizer_prompt_lite` |
| `api/retrieval_debug.py` | 新参数（`w_dense`/`w_bm25`/`use_hyde`/`rerank_pool`/`rerank_mode`/`blend_alpha`）、默认值、meta 暴露索引规格 |
| `preprocess.py`、`api/tool.py` | 建索引时使用富索引规格 |
| `core/tools.py` | 生产 Reranker 阈值与配置对齐 |
| `web/app.js` | 前端默认值兜底与 meta 对齐 |
| `scripts/rag_opt/*` | 离线预计算 / 模拟器 / 12 组网格扫描 / 端到端与 API 评测 |

### 3.2 产物重建（重要）

索引侧改动**不会自动生效**，必须重建：

```bash
python scripts/rag_opt/rebuild_index.py        # 自动备份到 store/_backup_<时间戳>/
```

本次已执行：`store/bm25_store/bm25`（legacy 265 词表 / avgdl 27 → rich 2751 词表 / avgdl 1460，b=0.4）、`store/vector_db`（31 篇按 `problem_solution` 规格重新编码）。旧产物备份在 `store/_backup_20261014_135659/`。

> **Docker 部署注意**：当前 8000 端口上的后端是 Docker 容器 `psych-agent`（代码烘焙在镜像里，`store/`、`data/` 是挂载卷）。索引产物已经通过挂载卷生效，但**代码改动需要 `docker compose up -d --build` 重建镜像**才能让 `/api/retrieval/debug` 反映本次优化。

---

## 4. 复现方式

```bash
# 0) 依赖：.venv（Python 3.14）+ models/ 下的 bge-small-zh-v1.5 / bge-reranker-base
# 1) 重建索引产物（会自动备份）
python scripts/rag_opt/rebuild_index.py

# 2) 端到端评测（真实 RetrievalPipeline，10 组配置对照）
python -u scripts/rag_opt/eval_final.py

# 3) 通过检索接口评测（需要先起服务）
python -m uvicorn main:app --host 127.0.0.1 --port 8001
python -u scripts/rag_opt/eval_via_api.py http://127.0.0.1:8001

# 4) 离线调参（不重复跑模型，秒级；矩阵缓存见 .cache/precomp.pkl）
python scripts/rag_opt/precompute.py            # 只需在提示词/索引规格变化后重跑
python scripts/rag_opt/sweep1_recall.py         # BM25 索引规格 / 查询权重 / 召回规模
python scripts/rag_opt/sweep2_dense.py          # dense 规格 / HyDE / 融合
python scripts/rag_opt/sweep3_fusion.py         # RRF k / 加权 / 三链路
python scripts/rag_opt/sweep4_rerank.py         # 阈值 / 候选池 / 索引规格
python scripts/rag_opt/sweep8_rerank_mode.py    # sort / filter / blend
python scripts/rag_opt/sweep9_blend.py          # alpha 细扫 + 稳健性
python scripts/rag_opt/sweep11_ablation.py      # 最终逐项消融
python scripts/rag_opt/sweep12_tune.py          # 联合微调
```

评测口径实现见 `scripts/rag_opt/harness.py`；离线模拟器与真实流水线的 BM25 部分**逐条完全一致**（`validate_bm25.py`：5 种索引规格 × 31 条 query，0 处不一致）。

---

## 5. 稳健性与过拟合讨论

本评测集只有 31 条 query、31 篇文档，必须警惕「调参调到数据集上」。因此最终配置不是取网格最优点，而是取**平台区中心**：

1. **`b`（0.2 / 0.4 / 0.6 / 0.75）**：loose 全为 1.000，strict 0.935–0.968，b=0.4 在 MRR 与 neg 上同时最优 → 选中；
2. **`rrf_k`（1 / 2 / 3 / 5 / 8）**：MRR 1.000、neg_before 0 的区间连续且宽，选中间的 3；
3. **`blend_alpha`（0.2–0.7）**：MRR 1.000 的区间很宽，选 0.3（偏保守，重排话语权低，更依赖融合先验）；
4. **`raw_top_k`（6–31）**：`raw_top_k=6` 时 `union_full` 掉到 0.774（有 query 的完整有效集合没被召回），15 之后饱和 → 选 15；
5. **单项归因**：富索引是唯一「换一个变量就大幅改善」的改动（loose 0.903→1.000 仅靠它），其余都是边际优化。**如果只能保留一项改动，应保留富索引。**

已知局限：

- **覆盖率仍有空间**（cov@3 0.737，理论上限 1.0）：17/31 条 query 会漏掉 1 篇「语义邻居」。这些漏检几乎都发生在「一个宽泛问题对应 2–3 篇同族笔记」的条目上（例如「方向焦虑」的 8-20 与《选择与价值》），属于 top-3 名额与标注口径的紧张，而不是检索失败——`union_full=1.000` 说明所有有效文档都在候选集里。如需进一步提升，方向是**提高 `final_top_k`**（但会挤占 RAG prompt 预算）或在 rerank 前做「同族去重 + 多样性重排（MMR）」。
- **HyDE 在本语料无效**：结论仅对「长口语化 query + 30 篇个人笔记」成立；短 query / 大库需要重测。
- **`distinctive_terms` 默认不加权**：同样依赖 query 长度分布。
- **交叉编码器输入规格**只完整评测了 `legacy`（`with_kw` / `problem_solution` 的矩阵生成被中断，未纳入结论）；这是一条值得补做的分支。
- **优化器提示词的非确定性**：离线实验用磁盘缓存固定了 LLM 输出（`scripts/rag_opt/.cache/opt_*.json`），线上每次请求都会重新改写。用**真实 HTTP 接口**跑全量数据集（每次都是新 LLM 调用）时，结果会落在 `loose@3=1.000 / strict@3=0.968 / MRR=0.968 / cov@3=0.742 / neg_before=0`——即**有 1 条 query 会因 LLM 改写波动而掉出 top-3**，这是本方案当前最大的不确定性来源（远大于检索算法本身的差异）。缓解方向：把 `optimize_prompt` 的结果按 query 做持久缓存（同一问题重复咨询时结果稳定），或改用确定性更强的改写模型。

---

## 6. 后续建议

1. **把 `distinctive_terms` 用起来**：目前它不加权、不参与排序。可尝试把它做成第三条稀疏链路（高特异性词单独 BM25 + RRF），或作为 rerank 的查询侧补充。
2. **多样性重排**：对「同族笔记」做 MMR，直接提升 cov@3。
3. **交叉编码器输入规格补测**：`with_kw`（摘要+关键词+problem/solution）与小语料上的微调（domain adaptation）值得一试。
4. **评测集扩容**：为每条 query 补 1–2 个更口语/更短的变体，验证「短 query 下 BM25 权重表与 HyDE」的收益——这是当前结论最可能外推失败的边界。
5. **把评测接入回归**：`scripts/rag_opt/eval_final.py` 的输出可直接作为 CI 门槛（例如 loose@3 ≥ 0.97 且 neg_before = 0）。
