# 4-B 按需检索门控 · 真实端到端验证报告

> 阶段：六阶段改造之阶段 4（Agentic 分支 / 门控 / 补救）
> 测试对象：阶段 4-A 落地的「retrieve 工具化 + consult 与检索解耦 + 门控版 agent_prompt」
> 测试方式：真实 LLM（deepseek-flash，API）+ 真实检索管线（本地 embedding/reranker）
> 版本：v5（追加阶段 4-C：`decompose_query` + `evidence_gap` 一次性补救 + 与硬预算共用；v4 检索语义修复：单边日期、清单级输出、topic 参数统一；v3 含 P1 `return_direct` 修复后重测 + 4-C 硬 Budget；v1/v2 于同日交付）

---

## 一、结论（先行）

1. **门控判定 5/5 全部正确**：真实 LLM 下，Agent 能准确判断"这轮要不要检索知识"，按需检索（Agentic RAG 的第一步）在真实链路成立。
2. **承接 / 澄清 / 感谢轮做到 0 检索**，不再像改造前那样每轮都无条件跑检索管线。
3. **P1（二次复述）已修复并验证**：`return_direct=True` 后，最终回复 = 工具原文，不再被外层 Agent 复述；`intent_type` 全轮稳定、引用 / 哨兵不再被改写。
4. **修复后新发现的次要问题（归入 P3）**：同一筛选请求，LLM 两次调用 `meta_filter_tool` 传参不同（一次带 `keyword`、一次不带），`keyword` 是 `keywords` 元数据字段的 AND 匹配且知识库无该词 → 0 命中。这是**工具调用参数漂移**，与门控 / return_direct 无关。
5. 回复质量良好：多轮上下文承接准确，引用了用户自己沉淀的原则（`cite` 正确）。
6. **阶段 4-C 已落地并验证**：`decompose_query` 可把复合求助拆成 1–3 条单维度子查询；Evaluator 新增 `evidence_gap` 四档判决；证据不足时**只补救一次**（分解重检 / 扩大召回），并与单轮 2 次硬预算共用，不存在检索循环；真实 E2E 补救分支已跑通（详见第六节）。
7. **回归中发现并修复外层分类抖动**：轮 3 偶发被判 `TOOL`（实测同一输入 6 次中 1 次），会跳过 `ensure_session` / `persist_history` 两个副作用；已补分类 prompt 规则 + 「判 TOOL 但无任何操作动词则纠正为 COUNSELING」的确定性兜底，复测 6/6 稳定、回归 5/5（详见第六节）。

---

## 二、测了什么、怎么测

- **不经过 HTTP**，直接调 `agent_service_entry(...)`（等价于线上 direct 链路，省掉端口 / 前端变量），完整走 Planner → Executor → AgentExecutor → 真实 LLM / 检索。
- **两路权威信号**：
  - 捕获 AgentExecutor verbose 的 `Invoking: <工具>` 行 = 真实工具调用序列（含本身不写 trace 的筛选原语）；
  - 每轮注入一个大容量本地 TraceTracker（上限 10 万，避免 500 条环形截断），取外层分类与证据消费情况。
- **5 轮对话**（同一 direct 会话）：首轮求理解 → 纯承接 → 新求方法 → 筛选对照 → 感谢。
- **修复后追加观测**：`reply_sentinel`（最终回复是否以工具哨兵开头）用于验证"输出即工具原文"。

---

## 三、每轮结果（P1 修复后重测）

| 轮 | 输入性质 | 期望门控 | 外层分类 | 实际工具序列 | 命中（原则,经历） | 耗时 | 门控 |
|---|---|---|---|---|---|---|---|
| 1 | 首轮长困扰，求理解 | retrieve→consult | COUNSELING | retrieve_knowledge → consult | (3, 0) | 31.9s | 通过 |
| 2 | 纯承接"心里挺慌、委屈" | 直接 consult | COUNSELING | consult（0 检索） | — | 22.2s | 通过 |
| 3 | 新具体求"怎么练习" | retrieve→consult | COUNSELING | retrieve_knowledge → consult | (3, 0) | 22.0s | 通过 |
| 4 | "找所有自我否定的日记" | 筛选工具 | TOOL | meta_filter | 0（LLM 多传 keyword） | 2.3s | 通过 |
| 5 | 感谢"清楚多了" | 直接 consult | COUNSELING | consult（0 检索） | — | 16.4s | 通过 |

> `intent_type`：轮 1/2/3/5 = `psychological_consult`（稳定）；轮 4 = `other`——因为该轮工具返回的是"未匹配到任何符合条件的文档"（无哨兵），Evaluator 按表驱动正确判为 other，**不是误判**。
> 每轮最终回复开头句仅出现 1 次（`reply_head_dup=1`），且回复即工具原文。

### v4 复核（检索语义修复后，同一 5 轮）

| 轮 | 工具序列 | 回复长度 | 耗时 | intent_type | 门控 |
|---|---|---|---|---|---|
| 1 | retrieve → consult（3,0） | 2185 | 29.4s | psychological_consult | 通过 |
| 2 | consult（0 检索） | 1283 | 15.1s | psychological_consult | 通过 |
| 3 | retrieve → consult（3,0） | 1713 | 26.6s | psychological_consult | 通过 |
| 4 | meta_filter | **377**（原 810） | 2.2s | meta_filter | 通过 |
| 5 | consult（0 检索） | 1965 | 15.8s | psychological_consult | 通过 |

- 门控正确 **5/5**，与前序版本一致；轮 4 从"全文堆叠 810 字"变为"2 篇清单 377 字"，且不再打印正文。
- 轮 4 查询"找所有关于自我否定的日记"由 LLM 只传 `topic_keyword`，`resolve_topics` 命中 `Self_Understanding`，无 0 命中、无兜底注记——参数漂移已从"事后兜底"前移为"schema 上消除"。

---

## 四、门控前后对比（人话说）

- **改造前**：外层一旦判定"心理倾诉"，`consult` 内部就无条件检索 15→3 再生成——哪怕用户只是"嗯""谢谢你"，也要跑一遍检索。
- **改造后**：Agent 自己判断——
  - 需要知识（问"怎么办 / 为什么 / 求方法"）→ 先 `retrieve_knowledge_tool` 拿证据 → 再 `consult` 基于证据回复；
  - 纯承接 / 澄清 / 确认 / 寒暄 → 直接 `consult`，0 检索纯共情。
- **实际命中**：轮 1 / 3 准确检索到"后发性共情""先安放情绪后陈述事实"等与当前困扰高度相关的文档；轮 2 / 5 完全不跑检索。

---

## 五、问题清单与处置

### P1（高）最终回复被外层二次复述 —— **已修复，验证通过**

- **现象（修复前）**：`consult` 已生成完整、带引用的最终回复，但 AgentExecutor 又让 LLM 重新复述一遍才作为输出；每轮多一次 LLM 往返，且两次测试 `intent_type` 不一致（哨兵被复述丢失时误判 `other`），行为不稳定。
- **修复**：`core/tools/registry.py` 对 6 个"产出最终回复"的工具加 `@tool(return_direct=True)`（`psychological_consult_tool`、`meta_filter_tool`、`precise_text_filter_tool`、`summarize_memory_tool`、`search_memory_tool`、`precise_memory_filter_tool`）；`retrieve_knowledge_tool` 为中间工具保持默认（Agent 需继续调 consult）。
- **验证（修复后 5 轮）**：
  - 门控仍 5/5；工具序列与修复前一致（检索轮 retrieve→consult，承接轮 0 检索）；
  - 输出 = 工具原文：轮 4 的回复就是 meta_filter 的原始返回串，轮 1/2/3/5 的回复是 consult 正文（哨兵前缀被 Evaluator 按设计剥离），**无二次复述**；
  - `intent_type` 轮 1/2/3/5 恒为 `psychological_consult`，不再随生成波动；
  - 端到端耗时未稳定下降（见下表）——耗时时长主要由 LLM 生成长度主导，但每轮确实少了一次 LLM 往返（省一次调用）；筛选轮 4.3s→2.3s 显著下降（此前要复述 781 字符）。

**修复前后耗时对比**：

| 轮 | 修复前耗时 | 修复后耗时 | 回复长度（前→后） |
|---|---|---|---|
| 1 | 31.9s | 31.9s | 1810 → 1964 |
| 2 | 17.0s | 22.2s | 1286 → 1881 |
| 3 | 25.4s | 22.0s | 2068 → 1908 |
| 4 | 4.3s | **2.3s** | 781 → 13（未匹配原文） |
| 5 | 12.7s | 16.4s | 1658 → 1407 |

### P2（中，观测层）trace 500 条环形截断 —— 未处理（计划内）

- 检索管线内部 trace 量大，超 500 条后砍掉开头，`classify` 等早期 trace 会丢失（仅影响线上排查，不影响功能）。
- 建议：关键路由 trace 单独留存或提高上限 / 分级存储。

### P3（低，质量）模糊筛选参数漂移 —— **已修复（v4 根治，原 4-C 兜底已被取代）**

- **现象**：用户问"帮我找所有关于自我否定的日记"，两次测试 LLM 给 `meta_filter_tool` 传参不同：上次 `{doc_type, topic_keyword}`（命中 2 篇 daily），这次 `{doc_type, topic_keyword, keyword}`（0 命中）。
- **实证**（直查 `filter_meta`）：`daily + topics LIKE %Self_Understanding%` → 2 篇；再加 `keywords LIKE %自我否定%` → 0 篇；纯 keyword → 0 篇。即知识库**没有**文档的 `keywords` 元数据含"自我否定"，LLM 多传 `keyword` 触发 AND 语义即空结果。
- **4-C 旧修法**：`meta_filter_tool` 保留双参数，0 命中时放宽 `keyword` 重查一次（事后兜底）。
- **v4 根治**：`meta_filter_tool` / `precise_text_filter_tool` 在 LLM 工具层**删除 `keyword` 参数**，只暴露 `topic_keyword`；原语内部先 `resolve_topics` 解析为标准主题，解析不到时由工具层自动降级按 `keywords LIKE` 查一次。模型不再有"传哪个"的选择，漂移根因消失。**前端检索页原语 `core/tools/knowledge.py` 的 `keyword` 参数不动**，现有检索 API 行为不变。
- **验证**：工具 schema 现为 `['doc_type','start_date','end_date','topic_keyword','emotion']`（precise 另含 `target_text`）；`meta_filter_tool.func(doc_type="daily", topic_keyword="自我否定")` → 2 篇、带清单头、无正文；5 轮回归轮 4 无兜底注记、`intent_type=meta_filter`。

### P4（中，代码层）检索无硬上限 —— 已修复（4-C 落地，验证通过）

- **现象**：检索次数此前只在 prompt 用自然语言约束（"最多再检索一次"），无代码层强制，LLM 不遵守时可能无限检索。
- **修复（4-C）**：硬 Budget 代码层限流——
  - `core/meta_db/context_meta.py`：常量 `RETRIEVE_BUDGET_PER_TURN = 2`；`SingleSessionState.retrieve_budget_left`（仅内存，不进 DB；`load_state` 逐字段赋值不覆盖；`clear_all` 重置）；
  - `core/orchestrator/executor.py` `_run_agent` 与 `core/orchestrator/fallback.py` `run_direct_fallback`：每次 `agent_executor.invoke` 前重置预算（每轮独立，防跨轮泄漏）；
  - `core/tools/registry.py` `retrieve_knowledge_tool`：调用前检查 `budget_left<=0` → 返回降级串"本轮检索预算已用尽…请直接 consult"，且不再递减。
- **验证**：单测 `budget=0` 时返回降级串且计数保持 0；5 轮真实回归正常轮（轮 1/3 各检索 1 次）不受影响，门控 5/5。

### P5（高，呈现）LLM 检索把文档全文打印进聊天 —— **已修复（v4）**

- **现象**：`meta_filter_tool` / `precise_text_filter_tool` 因 `return_direct=True`，把命中文档的**完整正文**（daily 打 `content`、weekly 打 problem+analysis+solution）直接作为最终回复输出；无条数/字数上限，与检索页的结构化列表（`doc_id` + 元数据 + 摘要）呈现割裂。500 篇规模下"找所有关于 X"可能一次吐出几万字。
- **修复**：两个工具的输出改为**清单级**——每条 `序号｜[doc_type]｜日期｜主题｜摘要前 60 字`，头部"共 N 篇（不同条件取交集，同一字段多值取并集）"，尾部"需要某篇全文：告诉我序号；或到检索页「知识检索」查看完整列表"。保留 `【模糊筛选匹配结果】` / `【精准文本匹配结果】` 哨兵，Evaluator 判定不变。
- **验证**：轮 4 回复 810 → 377 字；单测断言输出不含 `原文档:`。

### P6（高，语义）单边日期条件被静默丢弃 —— **已修复（v4）**

- **现象**：`core/meta_db/knowledge_meta.py::filter_meta` 原为 `if start_date and end_date: ... BETWEEN`；只填起始或只填结束日期时**日期条件整条消失**，结果按其余条件全量返回。检索页是两个独立日期输入框，用户只填一个时主观感受就是"日期没生效、像并集"。
- **修复**：
  - 单边改开区间：只有 `start_date` → `date >= ?`；只有 `end_date` → `date <= ?`；两端仍 `BETWEEN`。跨字段 AND 语义不变。
  - 顺带修复日期格式：库内历史日期存在 `2026-7-11`（不补零），TEXT 字符串比较会跨月误判（`'2026-10-01' < '2026-9-01'`）。`KnowledgeMetaDB.__init__` 建表后执行幂等迁移，统一为 `YYYY-MM-DD`；写入侧（`insert_or_update` / `batch_upsert`）同步规范化。
- **验证**：迁移后 31 篇全部标准格式；`start=2026-08-01` → 5 篇（8 月 4 篇 + 9 月 1 篇，无 7 月）；`end=2026-07-31` → 2 篇（均为 7 月）；`BETWEEN 7 月` → 2 篇；断言全部无越界。

### 语义规则现状（修复后，供后续参考）

| 维度 | 规则 |
|---|---|
| 跨字段 | AND（类型 ∩ 日期 ∩ 主题 ∩ 关键词 ∩ 情绪） |
| 主题多值 | OR（任选其一命中） |
| 情绪多值 | OR（主/次情绪任一命中） |
| 关键词多值 | AND（每个词都需包含；仅前端检索页暴露） |

前端检索页已追加一行说明："不同字段之间取交集；同字段多值中「主题/情绪」取并集，「关键词」需同时包含。"

---

## 六、阶段 4-C：证据不足补救（`decompose_query` + `evidence_gap`）

**设计边界**：心理场景的知识库是「可选参照」而非事实唯一来源。证据不足不等于回复失败，因此补救只做**一次**，且不追求"检索到满意为止"。

### 6.1 判定与动作

| 环节 | 规则 |
|---|---|
| 证据充分性 | 空结果 → `empty`；`max(cross-encoder 分) < 0.05` → `weak`（**取最高分**，不取首条：实测存在 0.2078/0.3954 的排名-分数倒挂）；问题含方法词（怎么/如何/练习/改善…）但 0 条 weekly → `no_principle`；否则 success |
| 阈值口径 | CE 概率对**查询措辞**高度敏感：同主题用户原话 0.75，LLM 改写句 0.08 / 0.19 / 0.26。因此 0.05 只当「基本无关」地板（实测离题查询 0.0045 / 0.0115），不当质量线 |
| 补救动作 | 拆出 ≥2 条子查询 → `decompose`（多查询检索后合并）；否则 → `expand`（`raw_top_k=25`、`rerank_pool=20` 扩大召回） |
| 合并口径 | 同一 `doc_id` 取最高分 + `0.05×覆盖次数`（封顶 1.0），同分按首次出现排名，截 `final_top_k=3` |
| 上限 | `remediation_count >= 1` → `limit_reached`；单轮预算 `<= 0` → `budget_exhausted`；一次补救只扣 1 次预算 |
| 补救后仍不足 | Executor 判 `evidence_gap` → 清零本轮预算、转纯理解回应，不再检索 |

### 6.2 改动清单

| 文件 | 改动 |
|---|---|
| `config/prompt_config.py` | 新增 `decompose_query_prompt`（输出 JSON 数组、1–3 条、单维度、只用原话、8–24 字、禁解释） |
| `core/helper/retrieval_config.py` | 新增证据/补救常量（weak 地板 0.05、方法词、子查询长度、补救 top_k/pool） |
| `core/tools/primitives.py` | `_extract_json_array`（字符串感知括号配对）+ `decompose_query`（首条恒为原问题；过短/异常/非数组退回单查询） |
| `core/helper/retrieval_pipeline.py` | `retrieve_documents_with_scores()`；`retrieve_documents()` 委托它（行为不变） |
| `core/helper/RAG_agent.py` | `retrieve_scored()` / `retrieve_multi()`（多查询合并，单查询等价原路径） |
| `core/orchestrator/evaluator.py` | `evaluate_evidence()` 四档判决、`evaluate_step()`（failure > evidence_gap > success） |
| `core/orchestrator/remediation.py` | 新文件：`merge_evidence()` + `remediate_once()`（预算/次数守卫，函数内延迟 import 防环） |
| `core/meta_db/context_meta.py` | `last_evidence` / `remediation_count`；`reset_turn_runtime()` 统一重置预算/证据/计数/`pending_docs` |
| `core/tools/registry.py` | `retrieve_knowledge_tool` 接证据分级 → 补救 → 二次分级；header 动态写明补救动作与剩余预算 |
| `core/orchestrator/executor.py` / `fallback.py` | 改调 `reset_turn_runtime()`；`evidence_gap` 分支清零预算、关闭后续检索 |
| `core/orchestrator/planner.py` | 分类 prompt 补「自身求助即使含方法词也判 COUNSELING」；新增操作动词白名单与确定性纠正 |
| `scripts/verify_4c_remediation.py` | 新验签脚本（7 项 A–G） |

### 6.3 专项验签（`scripts/verify_4c_remediation.py`，7/7 PASS）

| 项 | 内容 | 结果 |
|---|---|---|
| A | `core.tools.registry` 与 `core.orchestrator.remediation` 双向独立导入无环 | PASS |
| B | 代码块/前后缀数组解析；首条=原问题；情境剥离；过短/异常/非数组/空输入兜底；子查询上限 | PASS |
| C | empty / weak / no_principle / ok 四档；分数倒挂时按 max 判 ok；无分数跳过 weak | PASS |
| D | `evaluate_step` 优先级：failure > evidence_gap > success | PASS |
| E | `merge_evidence` 去重与排序；`retrieve_multi` 单查询等价 `retrieve_scored` | PASS |
| F | 预算 0 → `budget_exhausted` 且不检索；已补过 → `limit_reached`；成功补救只扣 1 次预算、计数 +1；第二次调用被上限拦住 | PASS |
| G | 真实 pipeline：`retrieve_documents_with_scores` 的 doc 顺序与 `run().final.doc_ids` 逐条一致，score_map 非空 | PASS |

### 6.4 真实 E2E 补救（强制触发，6/6 断言通过）

首轮 5 轮回归未出现补救 header（按当时阈值判定为未触发）；为验证线上分支，在阈值仍为 0.20 时临时把它抬到 0.95 后直调 `retrieve_knowledge_tool.func(...)`：

```
【知识检索证据】命中 3 条心理原则、0 条过往经历。
（首次证据不足，已自动分解为 2 条子查询重检一次）
本轮检索预算已用尽，不要再调用本工具；请直接调用 psychological_consult_tool…
```

| 断言 | 实测 |
|---|---|
| header 含补救说明 | ✅ |
| 预算 2 → 0（首次 1 + 补救 1） | ✅ |
| `remediation_count = 1` | ✅ |
| 动作 `decompose`，子查询 2 条（原问题 + 重检改写） | ✅ |
| `pending_docs` / `referenced_doc_ids` 均为 3 篇 | ✅ |
| 补救后 `last_evidence` 仍为 `evidence_gap`（阈值被强制 0.95，属预期） | ✅ |

> 说明：该次为**人为抬高阈值**的强制触发，不代表日常会频繁补救。

### 6.5 5 轮门控回归（v5，阈值 0.05）

第一次回归出现 **4/5**：轮 3 外层判 `TOOL`（工具序列仍是 retrieve→consult，回复正常），复测同一输入 6 次为 `5 COUNSELING / 1 TOOL`，确认是分类器抖动而非逻辑回归。修复后复测 **6/6 COUNSELING**，再跑完整回归（已采集每轮证据状态）：

| 轮 | 分类 | 工具序列 | 命中（原则,经历） | 证据状态 / top | 回复长度 | 耗时 | 门控 |
|---|---|---|---|---|---|---|---|
| 1 | COUNSELING | retrieve → consult | (3, 0) | success / 0.257 | 2206 | 28.7s | 通过 |
| 2 | COUNSELING | consult（0 检索） | — | — | 1961 | 19.8s | 通过 |
| 3 | COUNSELING | retrieve → consult | (3, 0) | success / 0.922 | 2028 | 26.6s | 通过 |
| 4 | TOOL | meta_filter | — | — | 379 | 2.0s | 通过 |
| 5 | COUNSELING | consult（0 检索） | — | — | 1886 | 14.0s | 通过 |

- 门控 **5/5**；全部 `reply_sentinel=None`，无二次复述。
- **无补救触发**（`remediation_action` 全为空），说明 0.05 阈值不会对正常改写查询误报。

### 6.6 阈值校准过程（发现并修正的一次误判）

调试证据字段时连续观测到同一主题的三个不同分数：

| 触发 | 工具收到的 query | top 分 | 当时判决 |
|---|---|---|---|
| 观测 A | `人际交往后反复回放自责，当时理性事后内疚` | 0.078 | weak（旧阈值 0.20） |
| 观测 B | 同上 | 0.195 | weak（旧阈值 0.20，仅差 0.005） |
| 观测 C | 同上 | 0.257 | success（新阈值 0.05） |

同一篇正确命中的文档（《避免“后发性共情”》）在三次运行中分数差 3 倍，根源是 prompt optimizer 每次改写的查询措辞不同，而 cross-encoder 概率对措辞敏感。对照实验：

| query | top 分 | 命中文档是否正确 |
|---|---|---|
| `人际交往后反复回放自责，当时理性事后内疚` | 0.195 | 正确（后发性共情） |
| `我该怎么练习先接住对方的情绪` | 0.413 | 正确 |
| `怎么改善睡眠质量，最近总是睡不好` | 0.0115 | 无关（任务管理类） |
| `如何做红烧肉` | 0.0045 | 无关 |

结论：0.20 会把「相关但措辞不同」的查询判成缺失，白跑一次补救并提前关掉本轮检索；已下调为 **0.05**，只拦「基本无关」。验签 C 项与常量断言同步更新，重跑 7/7。

### 6.7 已知限制（如实记录）

1. 阈值 0.20 时轮 1 曾**自然触发**一次 `expand`（top 0.078 / 0.195 均判 weak），但事后确认是误判（见 6.6）；下调 0.05 后最新 5 轮不再触发。`decompose` 分支仍只由单测（B/F）与强制 E2E（6.4）覆盖，未在真实多轮中自然出现。
2. CE 分数随措辞波动（同主题 0.078~0.922），0.05 是地板而非质量线；极端措辞仍可能误判，但代价被硬预算限制为「每轮最多一次补救」。
3. `expand` 动作复用同一 query、只扩大候选池，**无法改变 query 本身的 CE 分**；它只在「正确文档原本排在 top_k 之外」时有效。分解重检（`decompose`）才是改写路径。
4. 一次补救 = 额外 1 次 decompose LLM 调用 + 2~3 次检索，最坏单轮耗时增加约 5–8s（受 `REMEDIATION_MAX_QUERIES=3` 与硬预算约束）。
5. 补救后仍为 `evidence_gap` 时本轮预算清零，Agent 只能基于既有证据回应；这是「知识库是可选参照」的设计取舍。

---

## 七、下一步（v5 之后）

**已落地（本报告 v4 随附检索语义修复）**：

1. ✅ **单边日期失效**：`filter_meta` 日期条件三分支（`BETWEEN` / `>=` / `<=`），历史日期补零迁移。
2. ✅ **LLM 检索输出全文**：两个筛选工具改清单级输出（序号/类型/日期/主题/摘要），不再打印正文。
3. ✅ **topic / keyword 职责重叠**：LLM 工具层删除 `keyword`，只留 `topic_keyword`；解析不到主题时自动降级 `keywords LIKE`；prompt 补参数纪律；前端检索页补语义说明。

**待做（阶段 5、6）**：

4. ✅ **已完成（v5）**：`decompose_query` 原语 + evaluator `evidence_gap` + 一次性补救分支（分解重检 / 扩大召回），与硬预算共用；验签 7/7、回归门控 5/5。
5. 阶段 5（会话并发按 conversation_id 建 Session）与阶段 6（评测文档）按六阶段表推进。
6. 可观测性 P2（trace 500 条环形截断）仍未处理，只影响线上排查。
7. 已知展示层小差异：检索页 / 清单的日期取自 `KNOWLEDGE_CACHE` 的 `Document.date`，与 DB 已规范化的值可能一先一后（重启缓存后一致），不影响筛选结果。

---

## 附：产物与改动

- 测试脚本：`scripts/gating_test/run_gating_test.py`（v2：新增 `reply_sentinel` 观测）
- 原始结果：`scripts/gating_test/gating_result.json`（v5：5/5）
- 阶段 4-C 验签脚本：`scripts/verify_4c_remediation.py`（7 项，7/7 PASS）
- 阶段 4-C 改动：`config/prompt_config.py`、`core/helper/retrieval_config.py`、`core/tools/primitives.py`、`core/helper/retrieval_pipeline.py`、`core/helper/RAG_agent.py`、`core/orchestrator/evaluator.py`、`core/orchestrator/remediation.py`（新增）、`core/meta_db/context_meta.py`、`core/tools/registry.py`、`core/orchestrator/executor.py`、`core/orchestrator/fallback.py`、`core/orchestrator/planner.py`
- v4 检索修复改动：
  - `core/meta_db/knowledge_meta.py`：`_normalize_date` + 历史日期幂等迁移；`filter_meta` 日期三分支
  - `core/tools/registry.py`：`_format_doc_brief` 清单输出；两个筛选工具删除 `keyword`、主题降级兜底
  - `config/prompt_config.py`：需求 1 / 2 补参数纪律与返回形态说明
  - `web/index.html`：检索页筛选表单后补交集 / 并集语义提示
- 前序修复改动：`core/tools/registry.py`（6 个最终回复工具 `@tool(return_direct=True)`，中间检索工具不动）
- 环境：chat / small 均为 `deepseek-flash`（API，key 由 `.env` 注入）；检索为本地 embedding / reranker。
