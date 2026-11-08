# PsychAgent Agent 架构改造方案（Plan-and-Execute + Agentic RAG）

> 版本：v1.0 · 2026-10-16
> 范围：`core/agent.py`、`core/tools.py`、`api/tool.py`、`core/helper/RAG_agent.py` 的编排/工具/基础设施层全面改造
> 目标：把「意图二分类 → 固定 AgentExecutor → 字符串哨兵解析」的死流程，升级为
> **Plan-and-Execute 骨架 + Agentic 灵活分支 + 结构化工具协议 + 依赖注入**的混合架构。

---

## 一、现状诊断（基于代码逐行核实）

### 1.1 `core/agent.py` —— 编排层的问题

| # | 问题 | 代码位置 | 后果 |
|---|---|---|---|
| A1 | **模块级全局 Agent 单例** | L38-48：`tool_list`/`router_llm`/`agent`/`agent_executor` 在 import 时创建 | 换模型只能靠 `reset_llm_cache` 手动 global 重建，重建依赖模块级 `tool_list`，状态难追踪 |
| A2 | **意图"确定目标"是一刀切二分类** | L70-104 `_is_counseling` + L173-191 分流 | 一次性二分类代替持续目标理解：复合意图（"总结下刚才的讨论并给出建议"）会被切成单标签；分类失败（L89-98）无条件降级为 COUNSELING，无评估无补救 |
| A3 | **"结果评估"是字符串哨兵扫描** | L212-261：8 个 `【...】` 标记逐个 `in`/`startswith` 判断 intent_type | LLM/工具输出稍变即错位；**真实 bug**：L253 `"【会话总结" in raw_output` 会把 `【会话总结失败】xxx`（异常路径文本）误判为成功 intent_type=summarize_memory |
| A4 | **会话状态全局单例 + 锁** | `SESSION_STATE`（context_meta）+ `with SESSION_STATE.lock` | 单会话假设：多会话并发时状态互相覆盖（锁只防竞争不防串扰），工具无法测试 |
| A5 | **双线模式编排重复** | guided 模式直调 `guided_reasoning`（tools.py），direct 模式走 agent_executor | 两套编排逻辑各自维护，路径分裂 |

### 1.2 `core/tools.py` —— 工具层的问题（用户点名）

| # | 问题 | 代码位置 | 后果 |
|---|---|---|---|
| B1 | **四重职责混在一个文件** | 基础设施单例工厂（L34-79）+ 工具实现（L351-607）+ `@tool` 包装（L610-805）+ 业务流程（`guided_reasoning` L259-348） | 文件 800+ 行、职责不分；改一处动全局 |
| B2 | **全局单例泛滥且更新不一致** | 6 个 `_GLOBAL_*` + 模块级 `meta_db` + `SESSION_STATE` | **真实 bug**：`reset_llm_cache`（L216-221）只清 3 个单例，漏清 `_GLOBAL_MEMORY_EMBEDDING`/`_GLOBAL_MEMORY_VECTOR_DB`/`_GLOBAL_MEMORY_META_DB`——换 embedding 模型后记忆链路仍是旧实例 |
| B3 | **工具隐式依赖全局会话** | `psychological_consult_tool`（L618-620）从 `SESSION_STATE` 隐式读 memories/chat/reasons | 不可测试、不可复用、不可多会话隔离；工具副作用不可见 |
| B4 | **业务流程混在工具文件** | `guided_reasoning`/`_auto_advise` 是完整引导流程，却放在工具文件，被 agent.py 直接调用 | 编排逻辑散落两处（agent.py + tools.py） |
| B5 | **同一逻辑三种入口** | 纯函数（`meta_filter`）→ `@tool` 包装（`meta_filter_tool`）→ API 直调（`api/tool.py` import 纯函数） | 输出格式（`【标记】文本`）为字符串扫描而生，协议脆弱 |

### 1.3 其他真实漂移点（本次新发现）

| # | 位置 | 问题 |
|---|---|---|
| C1 | `core/helper/RAG_agent.py` L86 `chat(raw_top_k=6, final_top_k=3)` | **生产心理咨询链路参数漂移**：`psychological_consult_tool` 调 `rag_agent.chat(...)` 不传 raw_top_k，走默认 **6**（v1 值），而检索优化已证明 raw_top_k=6 会掉召回（union_full 0.806→1.000）。上一轮只修了 `tools.py:278` 的 guided 链路，这条 RAG_agent 链路还漏着 |
| C2 | `api/tool.py` L44 `if "【会话总结失败】" in tool_result` | 字符串哨兵扩散到 API 层；失败/成功判定靠文本子串 |

---

## 二、目标架构（三层 + 一个容器）

```
┌──────────────────────────────────────────────────────┐
│ 编排层 core/orchestrator/  (Plan-and-Execute + ReAct) │
│   Planner   把用户请求 → 步骤计划（含是否需要检索）     │
│   Executor  逐步执行；关键决策点支持 Thought/Action/   │
│             Observation 局部循环（Agentic 分支）        │
│   Evaluator 每步结果结构化评估（success/evidence/       │
│             need_more）→ CRAG 式补救门控               │
│   Budget    预算护栏：最大步数 / 成本 / token 上限      │
│   Fallback  Agent 失败 → 降级确定性链路（现状保底）     │
└───────────────┬──────────────────────────────────────┘
                │ 结构化 ToolCall / ToolResult 协议
┌───────────────▼──────────────────────────────────────┐
│ 工具层 core/tools/  (原语化、无全局状态)               │
│   registry.py  ToolRegistry：注册 / 发现 / 执行 / schema │
│   primitives/  search_notes / filter_notes /          │
│                search_memories / summarize_session /  │
│                decompose_query / recall_history / ... │
│   io.py        ToolResult(ok, data, evidence, msg)    │
│                所有工具依赖通过参数显式传入             │
└───────────────┬──────────────────────────────────────┘
                │ 依赖注入（不直接 import 单例）
┌───────────────▼──────────────────────────────────────┐
│ 基础设施层 core/infra/  (单例收敛为容器)               │
│   context.py  AppContext：统一持有 db / embedding /    │
│               retriever / reranker / llm / summarizer  │
│               rebuild() 一处重建，消灭 _GLOBAL_* 六兄弟 │
│   session.py  Session：显式会话对象（对话历史/记忆/     │
│               引用文档），随请求传入，支持多会话隔离    │
└──────────────────────────────────────────────────────┘
```

核心原则：
1. **工具原语化 + 结构化 I/O**：工具只做一件事、只依赖显式参数、返回 `ToolResult(ok, data, evidence, msg)`。**消灭所有 `【标记】` 哨兵**。
2. **编排与工具解耦**：Planner/Executor/Evaluator 只认识 ToolSpec 与 ToolResult，不认识具体实现。
3. **依赖注入替代全局单例**：所有组件经 `AppContext` 注入；`reset_llm_cache` 变成 `app_context.rebuild()`，一处生效。
4. **评估进循环**：每步工具调用后显式评估（成功/失败/证据不足），失败或证据不足触发补救（扩名额、分解查询、换工具），而不是等最后字符串扫描。
5. **预算护栏 + 降级保底**：Agent 有成本上限；超限或异常回退到当前的确定性链路（现状代码先保留为 Fallback）。

---

## 三、改造步骤（6 阶段，每阶段独立验收、可回退）

### 阶段 0：现状加固（半天，纯修 bug，不动架构）
- 修 `core/tools.py:reset_llm_cache`：清空全部 6 个 `_GLOBAL_*`（补 3 个漏清的）。
- 修 `core/helper/RAG_agent.py:chat`：默认参数改为吃 `RC.DEFAULT_RAW_TOP_K / DEFAULT_FINAL_TOP_K`（消除 C1）。
- 修 `core/agent.py` L253：`"【会话总结"` 前缀匹配排除失败文本（消除 A3 的 bug 分支）。
- **验收**：`python scripts/rag_opt/eval_final.py` 指标不回落；模型切换 API 后组件一致性手工验证。

### 阶段 1：基础设施收敛（1 天）
- 新建 `core/infra/context.py`：`AppContext` 容器，把 `_get_memory_*` / `get_global_rag_agent` / `meta_db` / `SESSION_STATE` 全部收编；提供 `rebuild()`。
- 新建 `core/infra/session.py`：`Session` 显式对象（full_chat_history / similar_memories / referenced_doc_ids / guided_reasons / mode），替代 `SESSION_STATE` 的隐式访问。
- `reset_llm_cache` → `app_context.rebuild()`；`core/agent.py` / `core/tools.py` 逐步改从 context 取。
- **验收**：grep 无新增 `_GLOBAL_*`；模型切换后所有组件（含 memory embedding）重建；现有对话回归。

### 阶段 2：工具原语化（1-2 天）
- `core/tools.py` 拆为 `core/tools/` 包：
  - `io.py`：`ToolResult` / `ToolSpec` 协议。
  - `primitives/`：`search_notes` / `filter_notes`（meta+precise 合并参数） / `search_memories` / `summarize_session` / `recall_history` / `decompose_query` / `consult_reply`。每个为纯函数，返回 `ToolResult`，**无 SESSION_STATE 隐式读**（会话经参数传入）。
  - `registry.py`：注册 + schema 生成（LangChain/OpenAI function 格式）。
  - `legacy.py`：保留 `@tool` 兼容包装（过渡期用），内部转调原语。
- `api/tool.py` 改吃 `ToolResult`（消除 C2 哨兵）。
- **验收**：全部调用点无 `【】` 字符串扫描；`/tool/*` 与 `/chat` 行为逐项回归一致。

### 阶段 3：编排层（Plan-and-Execute 骨架，2-3 天）
- 新建 `core/orchestrator/`：
  - `planner.py`：LLM 生成步骤计划（步骤 = 工具名 + 参数 + 是否需要检索）。直接模式与引导模式都变成"一个计划"（引导模式 = 检索→提问→循环→总结 的计划）。
  - `executor.py`：顺序执行步骤，每步 `ToolResult` 进入上下文。
  - `evaluator.py`：评估每步结果（success / evidence_gap / failure）；evidence_gap → 触发补救（阶段 4 接入）。
  - `budget.py`：最大步数、累计成本上限。
  - `fallback.py`：异常/超预算 → 回退当前 `guided_reasoning` / `agent_executor` 保底链路。
- `core/agent.py` 重构为 `Orchestrator` 的使用方：`agent_service_entry` 只做会话解析 + 调 Orchestrator + 结构化返回；`_is_counseling` 二分类删除，改为 Planner 内"是否需要检索"决策。
- `guided_reasoning` 从 `core/tools.py` 迁到 `orchestrator/plans/guided_plan.py`。
- **验收**：31 条既有对话/工具用例回归；复合意图（"检索+总结"）手工用例通过；字符串哨兵解析路径已无。

### 阶段 4：Agentic 灵活分支 + 检索门控 + 补救（2-3 天）
- `executor.py` 支持**局部 ReAct 循环**：计划中标记为 `flexible` 的步骤，允许 Thought→Action→Observation 多轮（替代"意图→固定工具"的死路）。
- **按需检索门控**（Self-RAG 思想，提示词实现）：Planner 产出 `needs_retrieval=true/false`；闲聊/确认类请求不触发检索，省成本省噪音。
- **CRAG 式补救**（复用上轮结论）：Evaluator 判定 evidence_gap 时：补救 A=扩名额（raw_top_k 15→30 / final_top_k 3→5）；补救 B=`decompose_query` 拆子问题合并。
- **预算护栏生效**：每会话最大 LLM 调用次数（默认 8）、单次最大工具步数（默认 12）；超限走 Fallback。
- **验收**：复合意图多轮用例（检索→发现不足→分解→合并→回答）通过；护栏触发路径可测；检索回归指标不回落。

### 阶段 5：会话显式化与并发（1 天）
- API 层按 `conversation_id` 创建/复用 `Session`；Orchestrator 每次调用接收 Session，工具不再摸全局。
- 移除 `SESSION_STATE.lock` 全局串行（多会话可并行）。
- **验收**：两个会话并发互不串扰（手工用例）；旧状态文件兼容迁移。

### 阶段 6：评测与文档（1 天）
- 检索回归：`scripts/rag_opt/eval_final.py` + `eval_via_api.py` 全绿。
- 新增编排层测试集：复合意图 / 多轮 / 失败注入（工具抛错→Fallback）/ 预算超限。
- 产出 `docs/architecture.md`：分层图、ToolSpec 清单、扩展指引（如何加新工具/新计划）。

---

## 四、风险与对策

| 风险 | 对策 |
|---|---|
| 改造期间线上不可用 | 阶段 0 先修 bug；阶段 1-2 保持旧路径并行（legacy.py 兼容包装）；阶段 3 起 Fallback 保底 |
| Agent 化引入成本/延迟 | Budget 护栏 + 按需检索门控 + 确定性 Fallback；默认 60% 请求仍走 Plan 骨架，仅复合意图走灵活分支 |
| 多会话改造破坏既有数据 | 阶段 5 做状态文件迁移 + 兼容读旧 `SESSION_STATE` 文件 |
| 检索质量回落 | 每个阶段结束跑 rag_opt 评测；阶段 4 的补救动作在 31 条+新增复合用例上双验证 |
| DeepSeek API 不稳定 | 门控/评估的 LLM 决策全部支持降级为规则（如：含"总结/查找/检索"关键词即触发检索） |

---

## 五、优先级建议

1. **阶段 0 立即做**（半天，三个真实 bug 现在就能修）。
2. **阶段 1 + 2 是本轮主体**（工具原语化 + DI 容器），收益最大：解决"tool.py 全局单例、隐式会话、四重职责"三大痛点，且不改对外行为，风险最低。
3. **阶段 3-4 是 Agentic 化核心**（P&E 骨架 + 灵活分支 + 检索门控），依赖前两阶段的结构化基础。
4. 阶段 5-6 收尾（并发 + 评测文档）。
