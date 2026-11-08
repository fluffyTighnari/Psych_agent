# 心迹 · 前端重构设计文档

> 版本：v1.0 · 2026-11-07
> 范围：`web/` 全量重构（Vue 3 + TypeScript + Vite）
> 前置结论：见本文 §1「后端契约与硬约束」——所有设计决策均由这些事实推导，不基于假设。

---

## 目录

1. [后端契约与硬约束](#1-后端契约与硬约束)
2. [技术选型与总体架构](#2-技术选型与总体架构)
3. [目录结构与模块边界](#3-目录结构与模块边界)
4. [API 层设计](#4-api-层设计)
5. [设计令牌系统](#5-设计令牌系统)
6. [组件清单与契约](#6-组件清单与契约)
7. [主对话：Turn 模型与 TurnTrace](#7-主对话turn-模型与-turntrace)
8. [主对话：流式渲染与消息呈现](#8-主对话流式渲染与消息呈现)
9. [主对话：ThreadRail 侧边导航](#9-主对话threadrail-侧边导航)
10. [关联图谱引擎](#10-关联图谱引擎)
11. [码字编辑](#11-码字编辑)
12. [记录页](#12-记录页)
13. [检索调试与排名迁移图](#13-检索调试与排名迁移图)
14. [无障碍规范](#14-无障碍规范)
15. [性能预算与工程化](#15-性能预算与工程化)
16. [迁移路线](#16-迁移路线)
17. [里程碑与验收标准](#17-里程碑与验收标准)
18. [需后端配合的契约变更](#18-需后端配合的契约变更)
19. [待决事项](#19-待决事项)

---

## 1. 后端契约与硬约束

以下每一条都在代码中核实过，**它们不是建议，是设计前提**。

### 1.1 接口清单（已实现的全部端点）

| 方法 | 路径 | 返回 `data` 结构 | 前端用途 |
|---|---|---|---|
| POST | `/chat` | `{intent_type, reply, raw_tool_output?}` | 一次性对话 |
| POST | `/chat/stream` | SSE：见 §1.3 | 流式对话 |
| GET | `/session/state` | 见 §1.4 | 会话恢复 |
| POST | `/session/clear` | — | 清空对话（保留 session_id、记忆库） |
| POST | `/session/reset` | — | 全清（新 session） |
| GET | `/tool/model` | `{small,large,chat}` 各含脱敏 api_key | 模型配置 |
| POST | `/tool/model/update` | — | 保存模型 |
| GET | `/ollama/list` `/ollama/ps` `/ollama/host` | 模型列表 / 运行中 | 抽屉 |
| POST | `/ollama/start` `/ollama/check` | — | 拉起模型 |
| POST | `/tool/search/meta-filter` | `{result: Document[]}` | 记录页 |
| POST | `/tool/search/text-filter` | `{result: Document[]}` | 记录页 |
| POST | `/tool/search/memory-filter` | `{result: Memory[]}` | 记录页 |
| POST | `/tool/search/memory-vector` | `{result: Memory[]}` | 记录页 |
| POST | `/tool/preprocess` | — | 预处理 |
| POST | `/tool/summarize` | `{summary_text}` | 一键总结 |
| POST | `/tool/article/save-daily` | `{save_path,file_name,type}` | 编辑页 |
| POST | `/tool/article/save-weekly` | `{save_path,file_name,type,title}` | 编辑页 |
| GET | `/knowledge/all` | `Document[]` | 记录页/图谱详情 |
| GET | `/memory/all` | `Memory[]` | 记录页/归档 |
| GET | `/graph/session-relation` | `{nodes[],links[]}` | 图谱 |
| GET | `/trace/all` | `{version,logs[]}` | 日志恢复 |
| GET | `/trace/latest` | `TraceItem \| null` | （未用） |
| GET | `/trace/stream` | SSE：`{version,logs[]}` @400ms | **TurnTrace 数据源** |
| POST | `/retrieval/debug` | 见 §1.5 | 检索调试 |
| GET | `/retrieval/documents` | `{documents[],doc_types,total}` | 检索调试 |
| GET | `/retrieval/documents/{id}` | `{document}` | 文档详情 |
| GET | `/retrieval/meta` | `{stages[],defaults{}}` | 开关与默认值 |

统一响应包装：

```ts
interface ApiResp<T> {
  code: number;     // 200 | 400 | 500
  msg: string;
  data: T;
  extra: Record<string, unknown>;
}
```

**注意**：业务失败也返回 HTTP 200，`code !== 200` 才是错误。API 客户端必须解包 `code`，不能只看 `res.ok`。

### 1.2 硬约束一：`/chat/stream` 是伪流式

```python
# api/chat.py:28-61（核实）
full_result = await loop.run_in_executor(None, agent_service_entry, ...)  # 全量跑完
# 然后才依次推送
yield meta → trace_all → reply_chunk(8字符切片…) → finish
```

**后果**：
- 首字延迟 = **完整生成耗时**（本地 Ollama 可达数十秒）。
- `reply_chunk` 的"逐字"是后处理切片，不是模型 token 流。
- 等待期前端**没有任何进度信号**，除非旁路订阅 `/trace/stream`。

**这是本文最重要的设计动因**：TurnTrace 不是锦上添花，而是填补这段空白期的唯一手段。

### 1.3 SSE 事件契约

`POST /chat/stream`（请求体同 `/chat`，`Content-Type: application/json`，**不是 EventSource**）：

```ts
type ChatStreamEvent =
  | { type: 'meta';      intent_type: string; ended: boolean }
  | { type: 'trace_all'; logs: TraceItem[] }
  | { type: 'reply_chunk'; content: string }
  | { type: 'error';     message: string }
  | { type: 'finish' };
```

分帧规则：`\n\n` 分隔事件，每个事件内 `data:` 前缀行拼接后 `JSON.parse`。

`GET /trace/stream`（标准 EventSource，每 400ms 一帧）：

```ts
interface TraceFrame {
  version: number;       // clear_trace() 时自增
  logs: TraceItem[];     // 仅新增项
}

interface TraceItem {
  stage: string;
  label: string;
  content: Record<string, unknown>;
  timestamp: number;     // Unix 秒（float）
  is_error: boolean;
  error_msg: string | null;
}
```

### 1.4 会话状态结构

```ts
interface SessionState {
  session_id: string;
  last_consult_query: string;
  last_role: string;
  mode: '' | 'direct' | 'guided';   // 首条消息后锁定
  mode_problem: string;             // guided 锚定问题
  mode_situation: string;
  guided_ended: boolean;
  full_chat_history: ChatHistoryItem[];
  similar_memories: Memory[];
  referenced_doc_ids: string[];
  guided_reasons: { role: 'guide' | 'user'; content: string }[];
}

interface ChatHistoryItem {
  role: 'user' | 'assistant';
  content: string;
  speaker?: 'advisor' | 'guide';   // 仅 assistant 有
}
```

### 1.5 检索调试响应结构

```ts
interface RetrievalDebugResp {
  latency_ms: number;
  enabled_pipeline: string[];          // 实际执行的阶段名序列
  optimized: {
    search_query?: string;
    match_topics?: string[];
    keywords?: string[];
    distinctive_terms?: string[];
    hyde_experience?: string;
    hyde_principle?: string;
  };
  stages: RetrievalStage[];
  final: {
    source: string;
    count: number;
    doc_ids: string[];
    results: RetrievalRankItem[];
  };
  final_summary: { source: string; count: number; doc_ids: string[]; label?: string };
  logs: TraceItem[];
}

interface RetrievalStage {
  name: string;                        // dense | bm25 | rrf | rerank | optimize_prompt
  label?: string;
  latency_ms?: number;
  results: RetrievalRankItem[];
}

interface RetrievalRankItem {
  rank?: number;
  score?: number;
  doc_id: string;
  doc: Document | null;                // 已由后端 doc_to_view 转换
}
```

### 1.6 图谱数据结构

```ts
type NodeType = 'session' | 'memory' | 'document' | 'reason';

type RelationType =
  | 'session_bind_memory'
  | 'session_ref_doc'
  | 'memory_ref_doc'
  | 'memory_related_memory'
  | 'reason_next'
  | 'session_bind_reason';

interface GraphNode {
  id: string;
  name: string;
  type: NodeType;
  summary?: string;
  source?: string;        // 仅 document
}

interface GraphData {
  nodes: GraphNode[];
  links: { source: string; target: string; relation: RelationType }[];
}
```

**注意**：`reason_next` / `session_bind_reason` 是**线性递进链**，语义上不是星状关联网络，渲染必须区分（见 §10.5）。

### 1.7 其余硬约束

| 约束 | 来源 | 设计影响 |
|---|---|---|
| 会话是**全局单例**（SQLite `current_session` 表 `id=1`） | `context_meta.py:49-63` | 无会话列表；侧边定位只能做**会话内导航** + 从 `/memory/all` 浏览归档 |
| `chat/stream` 与 `_ensure_session` 各调一次 `clear_trace()` → version 连跳两次 | `chat.py:26`、`executor.py:35` | **不能按 version 跳变重置视图**，会让 `classify_intent` 丢失 |
| 静态站点挂载在 `/` | `main.py:39` | 引入 SPA 后非根路径 404；用 hash 路由或后端加 fallback |
| 引导结束回复内拼了 `【建议总结】\n{report}` | `guided_plan.py:140` | 一条消息含两段语义，需拆分渲染 |
| 引用 ID 同时覆盖文档与记忆 | `primitives.py:108`、`RAG_agent.py:29` | cite chip 解析必须支持双类型 |
| trace 阶段名：`classify_intent / session_init / tool_call / tool_result / evaluate / session_save / guided_reasoning / preprocess / chat / chat_stream` | 全仓 grep 核实 | 阶段映射表需覆盖未知阶段兜底 |

---

## 2. 技术选型与总体架构

### 2.1 选型

| 层 | 选择 | 理由 |
|---|---|---|
| 构建 | **Vite** | 无历史包袱；`build.outDir` 可指向 `web/dist`，后端只需改一行挂载路径 |
| 框架 | **Vue 3 + `<script setup>`** | 现有代码全是模板字符串拼 DOM，模板系统改造收益最大；Composition API 适合三条并发数据流 |
| 语言 | **TypeScript（strict）** | 后端契约有三套复杂嵌套结构，类型是主要防线 |
| 状态 | **Pinia** | 有明确的跨视图域状态（会话/turn/图谱/检索），需 devtools 与时间旅行调试 |
| 路由 | **vue-router（hash 模式）** | 规避静态挂载的 404 问题；无需后端改动 |
| CSS | **原生 CSS + 设计令牌**，`<style scoped>` | 不上 Tailwind：这个项目的视觉是高度定制的"纸感编辑风"，原子类反而会稀释它 |
| 图表 | **自绘 Canvas**（排名迁移图、图谱） | 与既有技能栈一致；不引入 ECharts（体积与主题适配成本高） |
| 编辑器 | **CodeMirror 6** | 体积小、中文输入法友好、Markdown 模式成熟；TipTap 会引入 md 双向转换的坑 |
| 字体 | **自托管子集 woff2** | 本地优先产品，Google Fonts CDN 在离线/内网必然失败 |

**不引入**：UI 组件库（Element Plus / Naive）。理由：现有视觉语汇（印章红、纸纹、衬线标题、超大留白）需要完全自控；组件库会把页面拖回通用后台观感。

### 2.2 数据流总览

```
                    ┌──────────────────────────────┐
                    │        Pinia Stores          │
                    │  session / chat / turn       │
                    │  graph / trace / retrieval   │
                    └───────▲──────────┬───────────┘
                            │          │
        ┌───────────────────┴──┐   ┌───▼────────────────┐
        │  core/stream         │   │  components / views │
        │  chat-stream.ts      │   │  （纯呈现，不做 IO） │
        │  trace-stream.ts     │   └────────────────────┘
        └───────────▲──────────┘
                    │
        ┌───────────┴──────────────────────────────┐
        │  core/api/client.ts（超时/取消/重试/解包） │
        └──────────────────────────────────────────┘
```

**关键原则：三条流的缝合点是 `turn` store。**

- `chat-stream.ts` 产出 reply 与 meta
- `trace-stream.ts` 产出阶段轨迹
- 二者都写入同一个 `Turn` 对象
- 图谱与 ThreadRail 从 `Turn` 反查引用关系和消息定位

---

## 3. 目录结构与模块边界

```
web/
├── index.html
├── vite.config.ts
├── tsconfig.json
├── package.json
├── public/
│   └── fonts/                    # 自托管 woff2 子集
└── src/
    ├── main.ts
    ├── App.vue
    ├── router.ts
    │
    ├── styles/
    │   ├── tokens.css            # 唯一真相：所有设计常量
    │   ├── base.css              # reset / 排版基线 / 滚动条
    │   ├── utilities.css         # 少量工具类（.is-hidden / .sr-only）
    │   ├── components.css        # 跨组件共享的原子（按钮/面板/卡片/徽章）
    │   └── views/                # 视图级样式（仅布局）
    │
    ├── core/
    │   ├── api/
    │   │   ├── client.ts         # fetch 封装
    │   │   ├── endpoints.ts      # 路径常量
    │   │   └── types.ts          # 后端 DTO（严格对应 §1）
    │   ├── stream/
    │   │   ├── chat-stream.ts
    │   │   └── trace-stream.ts
    │   ├── graph/
    │   │   ├── engine.ts         # 生命周期 + 主循环
    │   │   ├── physics.ts        # 力模型 + Barnes-Hut
    │   │   ├── renderer.ts       # 分层绘制
    │   │   ├── interaction.ts    # 指针/滚轮/键盘
    │   │   ├── layout.ts         # 标签避让、入场动画
    │   │   └── theme.ts          # 从 CSS 变量读色
    │   ├── domain/
    │   │   ├── turns.ts          # 历史 → Turn[] 的还原
    │   │   ├── citations.ts      # [[cite:]] / [[guide:]] 解析
    │   │   ├── stages.ts         # trace stage → 语义阶段映射
    │   │   └── markdown.ts       # md 渲染与安全 HTML
    │   └── utils/
    │       ├── debounce.ts
    │       ├── format.ts         # 时间/分数/字数
    │       └── clipboard.ts
    │
    ├── stores/
    │   ├── session.ts            # 会话状态 + 模式锁定
    │   ├── chat.ts               # 消息列表 + 发送动作
    │   ├── turn.ts               # ★ Turn 聚合（核心）
    │   ├── trace.ts              # 原始 trace 缓冲（调试视图）
    │   ├── graph.ts              # 图数据 + 高亮焦点
    │   ├── models.ts             # 模型配置
    │   └── retrieval.ts          # 检索调试
    │
    ├── components/
    │   ├── ui/                   # 无业务语义的原子组件
    │   │   ├── AppButton.vue
    │   │   ├── AppPanel.vue
    │   │   ├── AppDisclosure.vue
    │   │   ├── AppPill.vue
    │   │   ├── AppField.vue
    │   │   ├── AppSelect.vue
    │   │   ├── AppToast.vue  + useToast.ts
    │   │   ├── AppModal.vue
    │   │   ├── AppDrawer.vue
    │   │   ├── AppSkeleton.vue
    │   │   ├── AppEmpty.vue
    │   │   └── AppIcon.vue        # sprite 索引
    │   ├── chat/
    │   │   ├── ChatMessage.vue
    │   │   ├── ChatComposer.vue
    │   │   ├── ModePicker.vue
    │   │   ├── TurnTrace.vue      # ★ 工具调用提示
    │   │   ├── TurnStageItem.vue
    │   │   ├── CitationChip.vue
    │   │   ├── AdviceReport.vue   # 建议报告卡
    │   │   └── ThreadRail.vue     # ★ 侧边导航
    │   ├── graph/
    │   │   ├── GraphCanvas.vue
    │   │   ├── GraphLegend.vue
    │   │   ├── GraphControls.vue
    │   │   ├── NodeInspector.vue
    │   │   └── GraphA11yList.vue  # 等价无障碍内容
    │   ├── writer/
    │   │   ├── MarkdownEditor.vue
    │   │   ├── WriteMetaBar.vue
    │   │   ├── DailyPanel.vue
    │   │   ├── WeeklyPanel.vue
    │   │   └── PickFromChat.vue
    │   ├── records/
    │   │   ├── FilterPanel.vue
    │   │   ├── ActiveFilters.vue
    │   │   ├── ResultCard.vue
    │   │   └── HighlightText.vue
    │   └── retrieval/
    │       ├── PipelineSwitches.vue
    │       ├── FinalResults.vue
    │       ├── StagePanels.vue
    │       ├── RankShiftChart.vue # ★ Canvas 斜率图
    │       └── DocBrowser.vue
    │
    └── views/
        ├── ChatView.vue
        ├── RecordsView.vue
        ├── WriteView.vue
        ├── TraceView.vue
        └── RetrievalView.vue
```

### 3.1 模块边界规则（硬性）

1. **`components/` 不做网络请求**，数据一律来自 props 或 store。
2. **`core/` 不 import Vue**（除了 `components/graph/GraphCanvas.vue` 里的挂载胶水）。图谱引擎必须是框架无关的纯 TS 类，才能独立测试。
3. **`stores/` 不 import 组件**。
4. 视图之间不直接互相调用，跨视图动作走 store 或 router。

---

## 4. API 层设计

### 4.1 `core/api/client.ts`

```ts
interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;        // 默认 8000；预处理/检索单独放宽
  retries?: number;          // 默认 1，仅对网络错误与 5xx 重试
}

class ApiError extends Error {
  constructor(
    public code: number,
    message: string,
    public detail?: unknown,
  ) { super(message); }
}

async function request<T>(path: string, opts?: RequestOptions): Promise<T>;
```

实现要点：

- **解包 `code`**：`json.code !== 200` → 抛 `ApiError(json.code, json.msg)`。
- **超时**：内部 `AbortController` + `setTimeout`；外部 signal 需与内部合并（`AbortSignal.any`）。
- **重试**：仅网络异常与 5xx；指数退避 `300ms * 2^n`；`AbortError` 不重试。
- **取消**：视图切换时统一中止。建议在 `router.beforeEach` 里 abort 上一视图的 `viewScope` 控制器。
- **长任务**：`preprocess` 超时设 0（不超时），但必须带可取消按钮。

### 4.2 `core/stream/trace-stream.ts`

```ts
class TraceStream {
  connect(): void;
  disconnect(): void;
  onFrame(cb: (frame: TraceFrame) => void): () => void;
  onStatus(cb: (s: 'open' | 'error' | 'closed') => void): () => void;
  get version(): number;
}
```

要点：

- 用原生 `EventSource`（GET）。
- **断线重连**：`EventSource` 自带重连，但需在 `onerror` 里更新状态徽标；连续失败 3 次后降级为 5s 轮询 `/trace/all`。
- **不按 version 重置（对话场景）**：`version` 变化只记录，不广播视图重置；是否重置由 `turn` store 决策（见 §7.3）。
- 全局单例，App 挂载时连接一次，卸载时断开。

### 4.3 `core/stream/chat-stream.ts`

```ts
interface ChatStreamHandlers {
  onMeta(m: { intent_type: string; ended: boolean }): void;
  onTrace(logs: TraceItem[]): void;
  onChunk(text: string): void;
  onError(msg: string): void;
  onFinish(): void;
}

async function streamChat(
  payload: { user_input: string; situation: string | null; mode: string | null },
  handlers: ChatStreamHandlers,
  signal: AbortSignal,
): Promise<void>;
```

要点：

- `fetch` + `res.body.getReader()` + `TextDecoder`。
- 缓冲按 `\n\n` 切帧；每帧解析 `data:` 行。
- `AbortError` 静默处理（用户主动停止），其他错误走 `onError`。
- 提供**停止生成**按钮 → `AbortController.abort()`。当前版本无此能力，用户只能干等。

---

## 5. 设计令牌系统

### 5.1 三层结构（强制）

```
base（物理色） → role（语义角色） → component（组件局部变量）
```

**规则：组件样式只能引用 role 层或自己的 component 变量，禁止直接引用 base 层。**

### 5.2 `tokens.css` 完整定义

```css
:root {
  /* ---------- base：物理色，仅 role 层可引用 ---------- */
  --c-paper:        #f4efe4;
  --c-paper-deep:   #ece4d3;
  --c-paper-card:   #faf6ec;
  --c-paper-ink:    #fdfbf5;

  --c-ink-900:      #2a231c;
  --c-ink-700:      #4a3f33;
  --c-ink-500:      #6c5f4e;
  --c-ink-400:      #746750;   /* 小字辅助文案下限，见 5.3 */
  --c-ink-300:      #a89a86;   /* 仅用于装饰/分隔，不得承载文字 */

  --c-red-600:      #a03820;
  --c-red-500:      #c24a2e;
  --c-red-200:      #e2b3a3;
  --c-gold-500:     #b08a4c;
  --c-gold-700:     #8a6a34;
  --c-teal-500:     #4e6d6a;
  --c-purple-500:   #7a5c8e;
  --c-green-500:    #4f8a5b;
  --c-danger:       #b4372e;

  /* ---------- role：语义角色 ---------- */
  /* 表面 */
  --surface:          var(--c-paper);
  --surface-raised:   var(--c-paper-card);
  --surface-sunken:   var(--c-paper-deep);
  --surface-overlay:  var(--c-paper-ink);

  /* 文字 */
  --text-primary:     var(--c-ink-900);
  --text-secondary:   var(--c-ink-500);   /* 正文辅助，5.4:1 */
  --text-tertiary:    var(--c-ink-400);   /* 小字提示，4.85:1 */
  --text-disabled:    var(--c-ink-300);
  --text-on-dark:     var(--c-paper-ink);
  --text-on-accent:   #fff7ee;

  /* 描边与分隔 */
  --border-strong:    #d5c8b0;
  --border:           #ddd2bd;
  --border-soft:      #e8dfcd;
  --divider-strong:   1px solid var(--border);
  --divider-soft:     1px solid var(--border-soft);
  --divider-dash:     1px dashed var(--border);

  /* 品牌与状态 */
  --accent:           var(--c-red-500);
  --accent-deep:      var(--c-red-600);   /* 小字必须用它，5.95:1 */
  --accent-soft:      var(--c-red-200);   /* 仅作背景/描边，不作文字 */
  --accent-ghost:     rgba(194, 74, 46, .10);
  --success:          var(--c-green-500);
  --warning:          var(--c-gold-700);
  --danger:           var(--c-danger);
  --danger-ghost:     rgba(180, 55, 46, .06);

  /* 图谱实体色 */
  --entity-session:   var(--c-red-500);
  --entity-memory:    var(--c-gold-500);
  --entity-document:  var(--c-teal-500);
  --entity-reason:    var(--c-purple-500);

  /* ---------- 字号：7 级 ---------- */
  --fs-2xs:  11px;    /* 时间戳、ID */
  --fs-xs:   12px;    /* 标签、徽章 */
  --fs-sm:   13.5px;  /* 次级正文、表单 */
  --fs-base: 15px;    /* 正文 */
  --fs-md:   17px;    /* 小节标题 */
  --fs-lg:   22px;    /* 视图标题 */
  --fs-xl:   28px;    /* 品牌/首页标题 */

  /* ---------- 行高：3 档 ---------- */
  --lh-tight: 1.35;
  --lh-body:  1.7;
  --lh-loose: 1.9;

  /* ---------- 字重：中文字形上限 700 ---------- */
  --fw-regular: 400;
  --fw-medium:  500;
  --fw-bold:    700;

  /* ---------- 间距：4px 标度，8 级 ---------- */
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 24px;
  --sp-6: 32px;
  --sp-7: 48px;
  --sp-8: 64px;

  /* ---------- 圆角：4 档 ---------- */
  --r-sm:   6px;
  --r-md:   10px;
  --r-lg:   16px;
  --r-pill: 999px;

  /* ---------- 阴影：4 级 ---------- */
  --ef-0: none;                                    /* 贴平面板，用描边 */
  --ef-1: 0 1px 2px rgba(42,35,28,.05),
          0 4px 14px rgba(42,35,28,.06);           /* 卡片 */
  --ef-2: 0 8px 28px rgba(42,35,28,.12);           /* 悬浮/抽屉 */
  --ef-3: 0 16px 56px rgba(42,35,28,.20);          /* 模态/浮层 */

  /* ---------- 层级 ---------- */
  --z-base:     0;
  --z-sticky:   100;
  --z-rail:     200;
  --z-drawer:   300;
  --z-modal:    400;
  --z-tooltip:  500;
  --z-toast:    600;

  /* ---------- 动效 ---------- */
  --dur-fast:   120ms;
  --dur-base:   180ms;
  --dur-slow:   320ms;
  --ease-out:   cubic-bezier(.2, .7, .3, 1);
  --ease-in-out: cubic-bezier(.4, 0, .2, 1);

  /* ---------- 交互态 ---------- */
  --focus-ring: 0 0 0 2px var(--surface-raised),
                0 0 0 4px var(--accent);

  /* ---------- 字体族 ---------- */
  --font-serif: "Fraunces", "Noto Serif SC", "Songti SC", serif;
  --font-sans:  "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  --font-mono:  "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
}

@media (prefers-reduced-motion: reduce) {
  :root {
    --dur-fast: 0ms;
    --dur-base: 0ms;
    --dur-slow: 0ms;
  }
}
```

### 5.3 对比度修正明细（已计算）

背景统一按 `--surface` `#f4efe4`（相对亮度 L ≈ 0.866）核定：

| 用途 | 现值 | 原对比度 | 新值 | 新对比度 |
|---|---|---|---|---|
| 小字提示（时间戳、ID、hint） | `--ink-faint` `#a89a86` | **2.40:1** ❌ | `--text-tertiary` `#746750` | **4.85:1** ✅ |
| 次级正文 | `--ink-soft` `#6c5f4e` | 5.45:1 ✅ | 保留 | 5.45:1 |
| 小号品牌红文字（如 `.results-count`） | `--accent` `#c24a2e` | **4.25:1** ❌ | `--accent-deep` `#a03820` | **5.95:1** ✅ |
| cite chip 文字（浅底深字） | `accent-deep` on `accent-soft` | ≈3.6:1 ❌ | `accent-deep` on `accent-ghost` | 5.6:1 ✅ |

**硬规则**：
- `--accent` 仅可用于 ≥17px 文字、描边、填充块。
- 任何 `<17px` 的红色文字一律 `--accent-deep`。
- `--text-disabled` 不得承载必要信息。

### 5.4 纸张颗粒改造

现状：`body::after` 全屏 `position: fixed; z-index: 9999; mix-blend-mode: multiply` —— 覆盖在弹窗与 Toast 之上，且降低文字锐度。

改造：
```css
.app-shell {
  background-image: url("/textures/paper-noise.svg");
  background-size: 140px 140px;
  background-repeat: repeat;
}
```
- 颗粒只作容器背景，不参与合成层堆叠。
- 生成一次性 SVG turbulence，`opacity` 通过纹理自身 alpha 控制（约 4%）。
- 弹窗/抽屉等浮层使用纯色 `--surface-raised`，不带颗粒，保证对比清晰。

### 5.5 字体加载

```ts
// main.ts
await Promise.all([
  document.fonts.load('600 22px "Noto Serif SC"'),
  document.fonts.load('400 15px "Noto Sans SC"'),
  document.fonts.load('700 13px "Fraunces"'),
]);
```

- 自托管子集 woff2；`@font-face` 带 `font-display: swap`。
- 加 `size-adjust` / `ascent-override` 对齐 fallback，抑制 CLS。
- **Canvas 绘制前必须 await**，否则首帧必然是回退字体，且不会自动重绘。

---

## 6. 组件清单与契约

### 6.1 UI 原子组件

| 组件 | Props | Emits | 说明 |
|---|---|---|---|
| `AppButton` | `variant: primary\|ghost\|danger\|quiet`、`size: sm\|md`、`disabled`、`loading`、`icon?` | `click` | `loading` 时保持宽度（spinner 绝对定位），避免布局跳动 |
| `AppPanel` | `title`、`hint?`、`elevation: 0\|1\|2` | `action`(slot) | 面板头/标题/提示/动作槽 |
| `AppDisclosure` | `open`、`label`、`hasDetail` | `toggle` | **统一所有可展开卡片**：trace 项、日志项、阶段卡、结果卡、文档卡 |
| `AppPill` | `active`、`tone: accent\|neutral`、`pressed?` | `click` | 用于模式切换、子模式、主题多选 |
| `AppField` | `label`、`hint?`、`error?`、`required?` | — | 统一 label/控件/slot/错误插槽 |
| `AppModal` | `open`、`title`、`labelledby` | `close` | `role="dialog" aria-modal` + 焦点陷阱 + Esc |
| `AppDrawer` | `open`、`side: right`、`width` | `close` | 同上 + 遮罩点击 |
| `AppToast` | — | — | `useToast()` 组合式函数；容器 `role="status" aria-live` |
| `AppSkeleton` | `lines`、`variant: text\|card` | — | shimmer，`prefers-reduced-motion` 下静止 |
| `AppEmpty` | `icon`、`title`、`desc`、`action?` | `action` | 三态空态的统一载体 |
| `AppIcon` | `name`、`size` | — | SVG sprite 索引，统一 24×24 / stroke 1.6 |

### 6.2 组件复用规则（硬性）

1. **所有可展开区域必须用 `AppDisclosure`**。现状有三套重复实现（`.result-card` / `.rd-doc` / `.rd-stage`/`.trace-item`），逻辑各写一遍。
2. **所有面板必须用 `AppPanel`**。禁止再手写 `.rd-panel-head` 这种结构。
3. **所有按钮必须用 `AppButton`**。`disabled` 状态在全变体下必须有视觉反馈（现状 `.ghost` 禁用态看起来仍可点）。
4. **禁止 `el.style.display`**。可见性一律 `v-if` 或 `.is-hidden` 类。
5. **禁止内联 `<style>` 中的裸色值**。

### 6.3 `AppDisclosure` 接口细节

```ts
interface DisclosureProps {
  open: boolean;
  label: string;
  meta?: string;          // 右侧时间/计数
  hasDetail: boolean;     // false 时不可展开、无 caret
  tone?: 'default' | 'error';
}
```

内部结构：`button[aria-expanded]` + 头部（caret / 标题 / meta）+ 内容区（`v-show` + 高度过渡，reduced-motion 下瞬时）。

---

## 7. 主对话：Turn 模型与 TurnTrace

### 7.1 Turn 数据结构

Turn 是本重构的**核心抽象**：从用户发送到 `finish` 的完整生命周期。

```ts
// core/api/types.ts
type TurnStatus = 'idle' | 'running' | 'done' | 'error' | 'aborted';

interface Turn {
  id: string;                    // 本地生成，nanoid
  index: number;                 // 会话内序号，从 0 开始
  createdAt: number;             // 毫秒

  // 输入
  userText: string;
  situation: string | null;
  mode: 'direct' | 'guided';

  // 输出
  speaker: 'advisor' | 'guide';
  reply: string;                 // 原始文本（含 [[cite:]] 标记）
  replyParts: ReplyPart[];       // 解析后的分段（见 §8.2）
  citations: Citation[];         // 去重后的引用集合

  // 过程
  stages: TurnStage[];           // 语义化的阶段轨迹
  startedAt: number;             // 毫秒
  finishedAt: number | null;
  status: TurnStatus;
  error: string | null;
  ended: boolean;                // 引导是否结束
  intentType: string;
}

interface TurnStage {
  key: StageKey;                 // 见 §7.2
  label: string;                 // 后端原始 label
  detail: StageDetail | null;    // 结构化摘要
  startedAt: number;             // 秒（来自 trace timestamp）
  endedAt: number | null;        // 下一阶段的时间，或 finish 时间
  status: 'pending' | 'active' | 'done' | 'warn' | 'error';
  raw: TraceItem;                // 保留原始，供展开查看
}

interface Citation {
  id: string;
  kind: 'document' | 'memory' | 'reason';
  index: number;                 // 显示用序号，按首次出现顺序
}
```

### 7.2 阶段语义映射

`core/domain/stages.ts`：

```ts
type StageKey =
  | 'classify' | 'session_init' | 'retrieve' | 'generate'
  | 'evaluate' | 'save' | 'guided' | 'other';

const STAGE_MAP: Record<string, { key: StageKey; title: string; icon: string }> = {
  classify_intent:  { key: 'classify',     title: '理解意图',   icon: 'compass' },
  session_init:     { key: 'session_init', title: '唤起记忆',   icon: 'archive' },
  tool_call:        { key: 'retrieve',     title: '处理中',     icon: 'tool' },
  tool_result:      { key: 'retrieve',     title: '检索与生成', icon: 'search' },
  evaluate:         { key: 'evaluate',     title: '校验证据',   icon: 'check' },
  session_save:     { key: 'save',         title: '保存会话',   icon: 'save' },
  guided_reasoning: { key: 'guided',       title: '引导推理',   icon: 'route' },
  preprocess:       { key: 'other',        title: '预处理',     icon: 'gear' },
  chat:             { key: 'other',        title: '对话',       icon: 'chat' },
  chat_stream:      { key: 'other',        title: '对话',       icon: 'chat' },
};
```

**未知 stage 兜底**：`{ key: 'other', title: stage, icon: 'dot' }`，不隐藏、不报错（后端新增阶段时不至于静默丢失）。

### 7.3 阶段归属算法（关键难点）

```
发送时：
  activeTurn = 新建 Turn{ status: 'running', startedAt: now, stages: [] }
  turnStartSec = now / 1000

trace 帧到达时：
  if (!activeTurn || activeTurn.status !== 'running') → 丢弃（或归入独立 trace 视图）
  for each item in frame.logs:
    if (item.timestamp < turnStartSec - 0.5) → 丢弃（上一轮的残留）
    appendStage(activeTurn, item)

  // 忽略 version 跳变 —— 见 §1.7
  // chat/stream 开头与 _ensure_session 内各 clear_trace() 一次，
  // 按 version 重置会丢掉 classify_intent。改用「activeTurn 存活期累积」。

chat-stream 事件到达时：
  meta      → activeTurn.intentType / speaker / ended
  trace_all → 与 trace 帧合并（按 timestamp+stage+label 去重）
  reply_chunk → 累积到 reply
  finish    → 定稿：给最后一个 stage 补 endedAt，status='done'，closeActiveTurn()
  error     → status='error'，error = message
```

**去重键**：`timestamp + stage + label + JSON.stringify(content)`（与现有一致，但集中在一处实现）。

**为什么不能用 version 重置**：`chat/stream` 先 `GLOBAL_TRACKER.clear_trace()`（version+1），随后 `_ensure_session` 又 `clear_trace()`（version+1）。若监听 version 变化就清空视图，第一个 version 跳变会清掉 `classify_intent`（它发生在 `_ensure_session` 之前）。现有代码就有这个隐患，只是被 `trace_all` 全量覆盖掩盖了。

### 7.4 TurnTrace 视觉规格

**进行中（active）**：

```
┌────────────────────────────────────────────────┐
│  ⟡ 处理过程                             4.2s ▾ │
│  ─────────────────────────────────────────────  │
│  ✓ 理解意图            COUNSELING       0.3s   │
│  ✓ 唤起记忆            匹配 2 条记忆     1.1s   │
│  ◐ 检索与生成          2 原则 · 1 经历   进行中  │  ← 脉冲
│  ○ 校验证据            等待中                   │
│  ○ 保存会话            等待中                   │
└────────────────────────────────────────────────┘
```

**完成（done）**：

```
┌────────────────────────────────────────────────┐
│  ✓ 已完成 · 4.2s · 引用 3 篇               ▸  │   ← 默认折叠
└────────────────────────────────────────────────┘
```

展开后为完整阶段列表 + 结构化详情。

**状态图标语义**：
| 状态 | 图标 | 颜色 |
|---|---|---|
| pending | `○` 空心圆 | `--text-disabled` |
| active | `◐` 半环（旋转动效，reduced-motion 下静止） | `--accent` |
| done | `✓` | `--success` |
| warn | `!` | `--warning` |
| error | `✕` | `--danger` |

**时长计算**：`endedAt - startedAt`。最后一个阶段用 `finish` 时刻 - `startedAt`。若无时间戳则不显示（**不伪造进度**）。

### 7.5 结构化详情提取

不同阶段从 `content` 提取不同摘要：

| 阶段 | 提取字段 | 渲染 |
|---|---|---|
| `classify_intent` | `content.result` | 徽章 `COUNSELING` / `TOOL` |
| `session_init` | `content.memory_count` | `匹配 N 条记忆` |
| `tool_result`（retrieve 完成） | `principle_count`、`experience_count` | `N 原则 · M 经历`，可点开列出 `doc_ids` |
| `tool_result`（evidence） | `evidence_status`、`top_score`、`remediation_action` | 证据充分/不足 + 分数；补救时显示"已自动分解查询"并标 `warn` |
| `evaluate` | `reason`、`top_score` | `is_error` 时 `error` 态 |
| `session_save` | `dialogue_turns`、`referenced_docs` | `N 轮对话 · 提及 M 篇` |
| `guided_reasoning` | `new_chain` | `新链` / `承接上一问` |

**设计意图**：这个 app 的用户最关心"我沉淀的知识被用上了吗"。所以 `tool_result` 的文档计数是**常驻可见信息**，不是调试信息。

### 7.6 错误与降级

- `trace` SSE 断开：TurnTrace 顶部显示"过程信息不可用"，但**不阻断对话**（reply 仍从 chat-stream 来）。
- 阶段缺失（比如后端没发 `classify_intent`）：不显示占位，只渲染实际收到的阶段。
- `chat-stream` 的 `error` 事件：气泡内显示错误卡片 + 重试按钮（重发同一条）。
- 用户点"停止"：`status='aborted'`，保留已收到的部分文本，TurnTrace 标"已中止"。

---

## 8. 主对话：流式渲染与消息呈现

### 8.1 增量渲染（修性能）

**现状问题**：每个 chunk 执行 `innerHTML = renderAssistantHTML(full)`，是 O(n²) 的转义 + 解析，还打断文本选区、导致滚动跳动。

**改造**：

```ts
// 累积纯文本 + 增量挂载
class IncrementalRenderer {
  private raw = '';
  private pending = '';        // 待处理的新增文本
  private scheduled = false;

  push(chunk: string) {
    this.raw += chunk;
    this.pending += chunk;
    if (!this.scheduled) {
      this.scheduled = true;
      requestAnimationFrame(() => this.flush());
    }
  }

  private flush() {
    this.scheduled = false;
    // 对 pending 做 [[cite:]] / [[guide:]] 检测：
    //   - 完整标记 → 先 flush 前置纯文本为 TextNode，再追加 chip 元素
    //   - 不完整标记（可能是跨 chunk 的半个标记）→ 保留在 buffer，等待下次
    // 只做 append，绝不重建已有节点
  }
}
```

**跨 chunk 标记处理**：若 `pending` 尾部匹配 `\[\[(cite|guide):[^\]]*$`（未闭合），保留该段不渲染，等下次拼接。

**选区保护**：追加 TextNode 不会清空选区，但若用户正在选中，暂停自动滚动（见 8.3）。

### 8.2 回复分段

```ts
type ReplyPart =
  | { kind: 'text'; content: string }
  | { kind: 'advice'; title: string; content: string };
```

规则：检测 `【建议总结】`（`guided_plan.py:140` 拼接的分隔符）。

- 若命中：前段 → `text`，后段 → `advice`，渲染为独立的**建议报告卡**。
- 报告卡样式：比普通气泡更宽的版式、左侧竖线强调、标题"建议总结"、右上角"存为周记"动作。
- 若未命中：整段 `text`。

**引用标记解析**（`core/domain/citations.ts`）：

```ts
const CITE_RE = /\[\[cite:([^\]\n]+)\]\]/g;
const GUIDE_RE = /\[\[guide:([^\]\n]+)\]\]/g;

function resolveCitation(id: string, ctx: {
  docs: Map<string, Document>;
  memories: Map<string, Memory>;
  graphNodes: Map<string, GraphNode>;
}): Citation {
  if (ctx.docs.has(id))     return { id, kind: 'document', index: 0 };
  if (ctx.memories.has(id)) return { id, kind: 'memory',   index: 0 };
  if (id.startsWith('reason_')) return { id, kind: 'reason', index: 0 };
  return { id, kind: 'document', index: 0 };   // 兜底
}
```

序号按**首次出现顺序**分配，同一 ID 复用同号。

### 8.3 智能贴底

```ts
// 仅当视口在底部 80px 内才自动跟随
const NEAR_BOTTOM_PX = 80;

function shouldFollow(el: HTMLElement) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
}
```

- 用户上翻时停止跟随，右下浮出「↓ 回到最新」胶囊按钮，带**新消息计数**。
- 滚动容器用 `scroll-behavior: auto`（程序滚动），按钮点击时用 `smooth`。
- 流式追加时若用户正在选中文本（`selection.anchorNode` 非空且在当前气泡内），**暂停自动滚动**。

### 8.4 消息呈现细节

| 元素 | 规格 |
|---|---|
| 头像 | 用户「我」= `--surface-inverse`；建议者「师」= `--accent`；引导者「引」= `--entity-reason` |
| 气泡 | 用户右对齐深底；assistant 左对齐浅底描边。最大宽度 74%（窄屏 88%） |
| 名字行 | `--fs-2xs` + 对应强调色，仅在连续同角色时隐藏重复 |
| cite chip | `[1]` + 类型图标；`--accent-ghost` 底 + `--accent-deep` 字；记忆型用 gold，推理型用 purple |
| 消息操作栏 | hover 显现：复制 / 查看引用 / 摘入周记。移动端常驻 |
| 时间 | 悬停显示，不常驻（减少噪音） |

### 8.5 Composer 改造

- 模式选择保留两卡，但**首条后锁定**时显示为一行状态条（当前问题 + 可"结束并生成建议"）。
- **显式结束引导**：guided 模式下提供「结束并生成建议」按钮 —— 当前完全依赖 LLM 自己吐 `【结束】`，用户无法主动收束，这是可用性缺口。
- 情境输入的展开/收起用 `AppDisclosure`，当前是手改 `style.display` 与按钮文字。
- 字符数提示（超长时提示会截断，后端 `problem` 有长度限制的段落）。
- `Ctrl/Cmd + Enter` 发送，`Enter` 发送 / `Shift+Enter` 换行（保持现状），但需在设置中可切换。
- **停止生成**按钮：发送后出现，点击 abort。

---

## 9. 主对话：ThreadRail 侧边导航

### 9.1 约束与定位

后端单会话 → 不做跨会话列表。ThreadRail 承担两件事：
1. **会话内导航**（主）
2. **归档记忆浏览入口**（次，数据来自 `/memory/all`）

### 9.2 折叠态（默认，48px 宽）

```
右侧悬浮刻度轨：

         │  ← 每条用户消息一个刻度
    ┌────┤
    │ ▪  │  ← 普通对话
    │    │
    │ ◈  │  ← 引导链节点（有 guide chip）
    │    │
    │ ●  │  ← 含引用的轮次
    │    │
    │ ▲  │  ← 当前视口所在
    └────┘
```

- 刻度形状编码：`▪` 普通 / `◈` 引导 / `●` 含引用 / `▲` 视口位置。
- `IntersectionObserver` 驱动当前高亮。
- hover 刻度 → 浮层显示该轮 Q 摘要（截断 40 字）+ 时间。
- 点击 → `scrollIntoView({block:'center'})` + 目标消息描边脉冲 1.2s。
- 不在对话宽度内占位（`position: absolute` 覆盖在右侧留白上）。

### 9.3 展开态（280px 面板）

按**引导链分组**，因为 `guided_reasons` 本身是线性结构，平铺会丢失语义：

```
┌ 对话大纲 ────────────── ✕ ┐
│ 🔍 [筛选轮次…]            │
├───────────────────────────┤
│ 第 1 问 · 引导链           │
│  ├ Q 我总觉得自己不够好    │
│  ├ A 你在害怕谁的评判？    │
│  ├ Q 可能是父母的期待      │
│  └ A 那这份期待现在还…     │
│                           │
│ ⚑ 建议报告 · 引用 3 篇     │
│                           │
│ 第 2 问 · 直接咨询         │
│  └ Q 怎么停止内耗          │
├───────────────────────────┤
│ 历史归档 ▸                │
└───────────────────────────┘
```

- 筛选：全部 / 仅引导 / 仅报告 / 含引用。
- 「历史归档」→ 抽屉列出 `/memory/all`，点开只读详情（标题/时间/摘要/洞察/引用文档/对话记录）。

---

## 10. 关联图谱引擎

### 10.1 现状问题（已核实）

| 问题 | 位置 | 后果 |
|---|---|---|
| RAF 永不停机 | `app.js:1108` | 视图切走后仍在跑，持续耗电 |
| 每帧 O(n²) 斥力 | `tick()` 双重循环 | 节点多时掉帧 |
| 每帧重算文档数 | `draw()` 内 `nodes.filter(...)` | 二次 O(n²) |
| 仅鼠标事件 | 无 pointer/touch | 触屏完全不可用 |
| 无缩放平移 | — | 无法看清局部 |
| hover 只放大自身 | — | "关联"语义未被交互表达 |
| tooltip 固定偏移 | `+16px` | 靠边溢出 |

### 10.2 引擎模块划分

```
core/graph/
├── engine.ts       GraphEngine：生命周期、状态机、对外 API
├── physics.ts      ForceSimulation：力模型 + Barnes-Hut 四叉树
├── renderer.ts     GraphRenderer：分层绘制
├── interaction.ts  InteractionController：pointer/wheel/keyboard
├── layout.ts       labelLayout：标签避让、入场时序
└── theme.ts        readGraphTheme()：从 CSS 变量读取色值
```

**`engine.ts` 对外 API**：

```ts
interface GraphEngineOptions {
  canvas: HTMLCanvasElement;
  onNodeClick(node: GraphNode): void;
  onNodeHover(node: GraphNode | null, evt: PointerEvent): void;
  onViewportChange?(scale: number): void;
}

class GraphEngine {
  setData(data: GraphData): void;
  start(): void;
  stop(): void;                       // ★ 必须存在且有调用点
  resize(): void;                     // ResizeObserver 驱动
  focusNode(id: string | null): void; // 外部高亮（cite chip 联动）
  zoomTo(fit: boolean): void;
  destroy(): void;
  dispose(): void;
}
```

### 10.3 生命周期与自动停帧

```ts
// 每帧记录总位移，低于阈值持续 N 帧则停机
let stillFrames = 0;
const STILL_THRESHOLD = 0.35;   // px/帧
const STILL_FRAMES_MAX = 20;    // 约 0.33s

function loop() {
  const moved = simulate();       // 返回本帧总位移
  render();
  if (moved < STILL_THRESHOLD) {
    if (++stillFrames > STILL_FRAMES_MAX) { stop(); return; }
  } else {
    stillFrames = 0;
  }
  raf = requestAnimationFrame(loop);
}

// 唤醒时机：setData / 拖拽 / hover / 缩放 / 高亮变化 / resize
function wake() { if (!running) start(); }
```

**视图切换**：`onBeforeUnmount` 调 `stop()` + `destroy()`；`onActivated` 调 `resize()` + `start()`。

### 10.4 物理模型

```ts
// 初始化：按类型分层初始化，而不是纯随机
function seedLayout(nodes: GraphNode[], W: number, H: number) {
  const center = { x: W / 2, y: H / 2 };
  nodes.forEach((n, i) => {
    switch (n.type) {
      case 'session':  // 固定中心
        n.fx = center.x; n.fy = center.y; break;
      case 'reason':   // 右侧弧线递进
        const a = -Math.PI / 3 + i * 0.35;
        n.x = center.x + Math.cos(a) * 180;
        n.y = center.y + Math.sin(a) * 180; break;
      case 'memory':   // 第一圈
        n.x = center.x + Math.cos(i * 2.4) * 110;
        n.y = center.y + Math.sin(i * 2.4) * 110; break;
      case 'document': // 第二圈，按被引用次数决定半径
        const r = 190 + Math.min(n.inDegree * 12, 70);
        n.x = center.x + Math.cos(i * 2.4) * r;
        n.y = center.y + Math.sin(i * 2.4) * r; break;
    }
  });
}
```

力模型：

| 力 | 参数 | 说明 |
|---|---|---|
| 斥力 | `k = 4800`（保留现值） | < 80 节点用 O(n²)；≥ 80 用 Barnes-Hut（θ = 0.9） |
| 连线弹簧 | 目标长度按关系类型 | `session_bind_memory` 130 / `session_ref_doc` 200 / `memory_ref_doc` 110 / `memory_related_memory` 95 / `reason_next` 90 |
| 向心 | 仅作用于无固定的非 session 节点 | 强度 0.008（保留） |
| 阻尼 | 0.88（保留） | |

```ts
// Barnes-Hut 四叉树（≥80 节点启用）
class QuadTree {
  insert(node: GraphNode): void;
  computeMass(): void;                        // 累计子节点质心与质量
  applyForce(node: GraphNode, theta: number): Vec2;
}
```

### 10.5 渲染分层

**静态层**（离屏 canvas，仅在 resize/主题变化时重绘）：
- 纸张网格底纹（极淡，24px 网格）
- 图例水印（可选，低透明度）

**动态层**（每帧）：

绘制顺序（决定遮挡关系）：
1. 所有连线（先画，被节点压住）
2. 非聚焦节点
3. 聚焦节点及邻接
4. 标签
5. hover 光晕

**聚焦高亮规则**（这是图谱的灵魂）：

```
hover / focus 某节点时：
  - 该节点 + 直接邻接节点：alpha = 1
  - 相关连线：alpha = 0.9，lineWidth 1.2 → 2.2
  - 其余节点与连线：alpha = 0.12
  - 邻接节点标签强制显示
```

**形状编码**（不只靠颜色，兼顾色盲与缩略图辨识）：

| 类型 | 形状 | 半径 | 特殊处理 |
|---|---|---|---|
| session | 双层光环圆 | 20 | 内圆实心 + 外环 `lineWidth 2` + 呼吸动画（reduced-motion 关闭） |
| memory | 实心圆 | 15 | — |
| document | 圆角方（`roundRect`） | 11 | 按 inDegree 增大 |
| reason | 菱形 | 12 | 沿递进链排列 |

**连线曲线化**：用二次贝塞尔，控制点沿法线偏移 `min(dist * 0.12, 40)`；同源节点的边统一偏转方向，减少交叉。

**虚线语义**（保留现有，但统一在 `theme.ts`）：
```ts
const LINK_STYLE: Record<RelationType, { color: string; dash: number[] }> = {
  session_bind_memory:   { color: 'var(--entity-session)',  dash: [] },
  session_ref_doc:       { color: 'var(--entity-document)', dash: [6, 5] },
  memory_ref_doc:        { color: 'var(--entity-memory)',   dash: [2, 4] },
  memory_related_memory: { color: 'var(--entity-memory)',   dash: [1, 3] },
  reason_next:           { color: 'var(--entity-reason)',   dash: [] },
  session_bind_reason:   { color: 'var(--entity-reason)',   dash: [4, 4] },
};
```

`theme.ts` 从 `getComputedStyle(document.documentElement)` 读取 `--entity-*`，**消除 JS 与 CSS 双份色值**（现状 `app.js:988` 硬编码）。

### 10.6 推理链单独成径

`reason_next` 是**线性递进**，与星状关联网络语义不同。设计：

- 在会话节点右侧渲染为**独立路径**，节点为菱形 + 序号（`① ② ③`）。
- 路径用实线连接，节点间距固定，不参与斥力模拟（只响应外层位移）。
- 视觉上与关联网络用留白分隔，加一条极淡的分区线。
- 这样"我已经想到第几步"一眼可见 —— 这是引导模式的核心进度表达。

### 10.7 交互

| 操作 | 行为 |
|---|---|
| `pointermove` 无拖拽 | hover 检测 → 聚焦高亮 + tooltip + 唤醒 |
| `pointerdown` 在节点 | 开始拖拽，节点固定（`fx/fy`） |
| `pointerdown` 在空白 | 开始平移画布 |
| `pointermove` 拖拽中 | 更新位置 / 平移偏移 |
| `pointerup` | 释放固定，带惯性衰减 |
| `wheel` | 以光标为中心缩放（`0.4x ~ 3x`） |
| `dblclick` | 复位视图（fit） |
| 双指捏合 | 缩放（`pointerdown` 计数 + 距离比） |
| 节点双击 | 打开 Inspector 并聚焦其邻接 |

**统一指针事件**：全部用 `pointerdown/move/up` + `touch-action: none` + `setPointerCapture`，不再写两套。

**tooltip 边界翻转**：
```ts
const OFFSET = 16;
let x = evt.clientX + OFFSET;
let y = evt.clientY + OFFSET;
if (x + tipW > innerWidth - 8) x = evt.clientX - tipW - OFFSET;
if (y + tipH > innerHeight - 8) y = evt.clientY - tipH - OFFSET;
```

### 10.8 与对话双向联动

| 触发 | 效果 |
|---|---|
| 对话里 hover cite chip | 图谱对应节点脉冲高亮（`focusNode(id)`），若图谱未展开则图例闪烁提示 |
| 对话里点击 cite chip | 打开 NodeInspector（不遮挡图谱） |
| 图谱里 hover 节点 | ThreadRail 标记引用了该节点的轮次 |
| 图谱里点击节点 | NodeInspector 内列出"引用此节点的对话轮次"，可点击跳转 |

`NodeInspector` 是**右侧侧滑面板**（从图谱区右缘滑入），不是居中模态 —— 居中模态会遮住用户正要看的图。

### 10.9 控件

图例下方一行紧凑控件（图标按钮 + `title`）：
- 聚焦模式切换：全部 / 会话+记忆 / 仅文档 / 仅推理链
- 缩放适配 / 复位 / 重新布局
- 显示/隐藏标签
- （可选）导出 PNG（`toBlob`）

### 10.10 无障碍

- `role="img"` + 动态 `aria-label`：「会话关联图谱：1 个会话、3 条记忆、12 篇文档、5 步推理」。
- `GraphA11yList`：可折叠的 `<ul>` 树形列表，等价描述所有节点与关系。默认折叠，供屏幕阅读器与键盘用户。
- 键盘：图谱容器 `tabindex="0"`；`Tab` 在图内节点间移动（管理式 tabindex），`Enter` 打开 Inspector，`+/-` 缩放，`0` 复位。
- 聚焦节点绘制明显的焦点环（不仅是 hover 光晕）。

---

## 11. 码字编辑

### 11.1 产品定位

这一页是**产品闭环的关键**：对话 → 记忆 → 周记原则 → 检索 → 更好的对话。当前四步在 UI 上完全割裂，是最大的价值浪费。

### 11.2 编辑器

**选型：CodeMirror 6**（`@codemirror/lang-markdown`）。

- 体积小（约 120KB gzip）。
- 中文输入法（IME）处理成熟 —— textarea 方案在长文本下列表/组合输入有兼容问题。
- 可扩展：后续加 `[[cite:]]` 高亮、任务列表、字数统计装饰。

**核心能力**：
- Markdown 语法高亮 + 实时预览切换（分栏 / 仅编辑 / 仅预览）
- 自动草稿：`localStorage` 每 2s 防抖保存，键 `draft:daily` / `draft:weekly`
- 保存成功后清除草稿
- 快捷键：`Cmd/Ctrl+S` 保存，`Cmd/Ctrl+Enter` 保存并预处理
- 专注模式：隐藏导航与头部，居中单栏（最大 68ch），可调字号

### 11.3 元信息条

编辑器上方一行常驻状态：

```
2026-11-07  ·  1,240 字  ·  约 4 分钟  ·  已自动保存 12:03
```

- 日期：Daily 用日期选择器；Weekly 用文件名输入（后端以文件名标识）。
- 状态区分：`编辑中` / `已自动保存 HH:mm` / `已保存至磁盘` / `保存失败`。

### 11.4 Weekly 结构化强化

三段改为**卡片流**，每段带完成度：

```
┌ ① problem · 问题 ──────────────── [已填写] ┐
│ 发生了什么？具体在什么情境下？              │  ← 引导式 placeholder
│ ┌────────────────────────────────────────┐ │
│ │                                        │ │
│ └────────────────────────────────────────┘ │
└────────────────────────────────────────────┘

┌ ② analysis · 分析 ─────────────── [未填写] ┐
│ 你当时的假设是什么？它经得起检验吗？        │
└────────────────────────────────────────────┘

┌ ③ solution · 方案 ─────────────── [未填写] ┐
│ 你验证有效的最小动作是什么？                │
└────────────────────────────────────────────┘
```

- 顶部进度 `填写 3/3`。
- 每段可折叠（`AppDisclosure`）。
- 保存前**预览生成的 md**。
- **同名覆盖警告**：后端 `open(path, 'w')` 直写，无版本。若检测到该文件名已有内容（可通过 `/knowledge/all` 比对），保存前二次确认。

### 11.5 从对话摘取（核心增量）

`PickFromChat.vue` —— 侧滑面板：

```
┌ 从对话摘取 ──────────────────────── ✕ ┐
│ [全部 ▾]  [搜索…]                      │
├────────────────────────────────────────┤
│ ⚑ 建议报告 · 11-07 14:32    [插入▾]    │
│   你真正害怕的不是任务本身，而是…       │
│                                        │
│ Q 我总觉得自己不够好        [插入▾]    │
│ Q 可能是父母的期待          [插入▾]    │
└────────────────────────────────────────┘
```

- `[插入▾]` 下拉选择插入到 problem / analysis / solution。
- 插入点为光标位置，带 `> 引用块` 前缀（Markdown 引用语法）。
- 这是本 app **最独特**的能力：把一次咨询沉淀成可被检索的原则。

### 11.6 保存后联动

保存成功 → Toast 内提供「立即预处理」动作 → 调用 `/tool/preprocess`（长任务，显示进度条 + 可取消）→ 完成后提示"已纳入检索"。

当前流程需要用户切到记录页手动点，断点明显。

---

## 12. 记录页

### 12.1 布局

- **≥1280px**：左侧筛选面板（280px 固定）+ 右侧结果流。
- **<1280px**：筛选收进可折叠条，顶部显示已选条件 chips。

### 12.2 筛选面板

- 分组：范围（类型/日期）→ 语义（主题/关键词/情绪）→ 模式专属（精准文本 / 自然查询）。
- 主题多选用 `AppPill` 网格，不用 checkbox（视觉更轻）。
- 已选条件实时反映为 chips，可单点移除、可"清除全部"。
- 底部固定「搜索」主按钮 + 结果计数预览。

### 12.3 结果卡

- **命中高亮**：`text-filter` 的 `target_text` 与关键词在摘要/正文中高亮（`HighlightText.vue`，用 `<mark>`，注意 XSS —— 必须转义后插入）。
- 元信息：类型徽章、日期、主题 chips、关键词 chips、情绪。
- 展开详情：正文 / problem-analysis-solution / 来源路径。
- **动作**：「在对话中问这篇」→ 切到对话页并在 composer 预填；「摘入周记」→ 编辑页预填。

### 12.4 三态空态

| 状态 | 表现 |
|---|---|
| 加载中 | 3–5 条骨架卡 |
| 加载失败 | 图标 + "加载失败：{msg}" + 「重试」按钮 |
| 确实为空 | 图标 + "还没有任何文档" + 「去写第一篇」按钮 |

**必须区分**。现状 `loadKnowledge` 失败只 `console.warn`，界面照样显示"未匹配到任何文档"，用户无法判断是没数据还是后端挂了。

### 12.5 性能

- 结果 > 60 条时启用虚拟滚动（`@tanstack/vue-virtual` 或自写 `useVirtualList`）。
- 筛选输入 150ms 防抖。
- 入场动画**只对首屏前 12 项**加 `animationDelay`，其余直接显示 —— 现状 30 条结果第 30 条要等 900ms。

---

## 13. 检索调试与排名迁移图

### 13.1 排名迁移图（本页最有价值的增量）

**问题**：当前需人肉在四个折叠面板间比对位次，无法回答"我的重排到底有没有用"。

**方案**：Canvas 斜率图（slope chart）。

```
  dense        bm25         rrf         rerank      最终
   #1 ─────────────────────────────────────────┐
   #2 ────╮                                    │
          ╰──────────────────────────────►  ●   #1 ✓ 进入最终
   #3 ────────────╮                            │
   #4             ╰────────x                   #2 ✗ 被阈值淘汰
   #5 ──► (新召回) ─────────────►  ●            #3 ✓
```

**数据映射**：
- 列 = `enabled_pipeline` 中的阶段 + `final`
- 行 = 所有出现过的 `doc_id` 的并集
- y 坐标 = `rank`（同阶段内按 rank 排序）
- 线 = 同一 `doc_id` 跨阶段的轨迹
- 颜色：
  - 进入 `final.doc_ids` → `--accent`（朱红，突出）
  - 中途消失 → `--text-disabled`（灰）
  - 首次出现于某阶段 → 起点标 `+`（新召回）
- 交互：hover 线 → 高亮整条轨迹 + 显示文档标题在所有阶段的 rank/score；hover 列头 → 高亮该阶段。
- 无数据阶段跳过并在列头标注 `—`（例如未启用 rerank）。

**实现要点**：
- 纯函数 `buildRankShiftModel(stages, final): RankShiftModel`，与绘制分离，便于单测。
- 绘制分层：轴/列头（静态）→ 轨迹 → 高亮层。
- DPR 适配 + `ResizeObserver`。
- 高度 = `max(8, docCount) * 22 + padding`，节点多时可滚动容器。
- 键盘：左右切换轨迹，画布旁提供等价表格（`<details>`）。

### 13.2 其余改造

- 开关卡片：用 `aria-pressed`，键盘可操作（现状 `input` 被 `display:none`，键盘完全不可用）。
- 参数区：每项加 `?` 悬浮说明（`raw_top_k` 是什么、`score_threshold` 默认值）。
- 运行中：按阶段渐进点亮（若后端能推阶段进度；否则用骨架 + 计时器）。
- **双阶段 diff**：选任意两阶段，并排显示位次变化，可只看"升/降/新增/消失"。
- 参数预设保存到 `localStorage`，命名后一键切换。
- 结果导出 JSON（便于离线分析）。

---

## 14. 无障碍规范

### 14.1 必须修复的硬伤（现状为零）

| 问题 | 位置 | 修复 |
|---|---|---|
| 三组核心控件键盘不可用 | `.mode-pill input` / `.topic-check input` / `.rd-switch input` 均 `display:none` | 改 `opacity:0; position:absolute; pointer-events:none` 保留可聚焦，用 `:focus-visible + span` 出焦点环；或 `appearance:none` 完全自绘 |
| 无全局焦点样式 | 各处 `:focus { outline: none }` | 统一 `--focus-ring`，仅对 `:focus-visible` 生效 |
| 无 ARIA | 全仓 0 处 | 见 14.2 |
| 无 reduced-motion | — | 全局媒体查询 + Canvas 动画开关 |

### 14.2 ARIA 基线清单

| 元素 | 属性 |
|---|---|
| 导航 | `nav` + `aria-current="page"` |
| 视图切换 | `role="tablist"` / `role="tab"` / `aria-selected` / `aria-controls` |
| 模态 | `role="dialog"` `aria-modal="true"` `aria-labelledby` + 焦点陷阱 + 关闭归还焦点 |
| 抽屉 | 同上 |
| Toast | 容器 `role="status"` `aria-live="polite"`；错误用 `aria-live="assertive"` |
| 折叠区 | `button[aria-expanded]` + `aria-controls` |
| 模式卡 / 开关 | `aria-pressed="true|false"` |
| 图谱 | `role="img"` + 动态 `aria-label` |
| 加载中 | `aria-busy="true"` |
| 骨架屏 | `aria-hidden="true"` + 容器 `aria-busy` |
| 链接状态 | 连接徽标变化用 `aria-live="polite"` 播报 |
| 图标按钮 | `aria-label`（不能只有 `title`） |

### 14.3 键盘可达性验收

纯键盘应能完成：切换视图 → 选模式 → 输入 → 发送 → 展开 TurnTrace → 点击引用 → 关闭 Inspector → 切换筛选 → 搜索结果 → 打开文档详情。

Tab 遍历中不得出现"焦点消失"节点（`display:none` 的 checkbox 就是这类）。

### 14.4 动效

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
  }
}
```

Canvas 侧：`matchMedia('(prefers-reduced-motion: reduce)')` 为真时，禁用呼吸/脉冲动画，力导向直接跳到稳定态（`simulate(300)` 批量迭代一次）。

---

## 15. 性能预算与工程化

### 15.1 预算

| 指标 | 目标 |
|---|---|
| 首屏 JS（gzip） | < 180KB |
| 首屏 CSS（gzip） | < 40KB |
| LCP（本地） | < 1.2s |
| CLS | < 0.05 |
| 图谱 ≤60 节点 | ≥ 55fps |
| 图谱静止 | 2s 内自动停帧 |
| 长回复（5000 字）流式渲染 | 无长任务 > 50ms |
| 列表 200 条 | 滚动 ≥ 50fps（虚拟滚动） |

### 15.2 分包

```ts
// router.ts —— 按视图懒加载
const routes = [
  { path: '/',            component: () => import('./views/ChatView.vue') },
  { path: '/records',     component: () => import('./views/RecordsView.vue') },
  { path: '/write',       component: () => import('./views/WriteView.vue') },
  { path: '/trace',       component: () => import('./views/TraceView.vue') },
  { path: '/retrieval',   component: () => import('./views/RetrievalView.vue') },
];
```

CodeMirror 与图谱引擎各自独立 chunk，只在进入对应视图时加载。

### 15.3 工程约束

- `tsconfig` 开 `strict`、`noUncheckedIndexedAccess`。
- ESLint + `eslint-plugin-vue`，禁止 `v-html`（除经 `markdown.ts` 消毒的单一出口）。
- `npm run build` 产物到 `web/dist`，由后端 `StaticFiles` 挂载。
- 开发：`vite` dev server + `proxy: { '/chat': 'http://127.0.0.1:8000', ... }`，避免 CORS。

### 15.4 安全

- 所有后端文本经 `esc()` 后插入；`v-html` 仅用于已消毒的 Markdown 输出。
- `markdown.ts` 使用 `markdown-it` + 禁用 `html: true`，或加 `DOMPurify`。
- `HighlightText` 必须"先转义再包裹 `<mark>`"，不能用正则直接替换原始 HTML。

---

## 16. 迁移路线

### 16.1 并行期

```
main.py（临时）：
  app.mount("/next", StaticFiles(directory=web/dist, html=True))
  app.mount("/", StaticFiles(directory=web/legacy, html=True))
```

- 旧版保留在 `web/legacy/`（`index.html` + `app.js` + `style.css` 原样搬入）。
- 新版在 `/next` 独立演进，功能对齐后切换根挂载。
- 切换后 `legacy/` 保留一个版本周期再删。

### 16.2 功能对齐清单

| 现有能力 | 新版对应 | 阶段 |
|---|---|---|
| 会话恢复 | `session` store + `/session/state` | P1 |
| 一次性 / 流式对话 | `chat-stream.ts` | P1 |
| 模式选择与锁定 | `ModePicker` | P2 |
| 情境补充 | `AppDisclosure` | P2 |
| 引用 chip | `CitationChip` + `citations.ts` | P2 |
| 图谱 | `GraphEngine` | P3 |
| 一键总结 | `AppButton` + `/tool/summarize` | P2 |
| 模型抽屉 | `ModelDrawer` | P4 |
| Ollama 启动 | 同上 | P4 |
| 记录页三种检索 | `FilterPanel` | P5 |
| 慢写页两模式 | `WriteView` | P4 |
| 流程日志 | `TraceView`（复用 `AppDisclosure`） | P3 |
| 检索调试 | `RetrievalView` | P5 |
| 节点详情弹窗 | `NodeInspector` | P3 |

---

## 17. 里程碑与验收标准

> **P0 已完成（2026-11-07）**，实测结论与实施偏差见 §17.9「P0 实施记录」。
> **P1 已完成（2026-11-07）**，见 §17.10「P1 实施记录」。
> **P2 已完成（2026-11-08）**，见 §17.11「P2 实施记录」。
> **P3 已完成（2026-11-08）**，含主对话富文本与执行链增强，见 §17.12。
> **P5 已完成（2026-11-08）**，记录页 + 检索调试 + 排名迁移图，见 §17.13。
> **P4 已完成（2026-11-08）**，CodeMirror 编辑器 + 从对话摘取 + 保存联动，见 §17.14。
> **P6 已完成（2026-11-08）**，无障碍归零 + 根挂载切换，**重构全部完成**，见 §17.15。

### P0 · 设计底座（3–5 人日）

- [ ] `tokens.css` 三层令牌落地，全量替换硬编码值
- [ ] 对比度修正（§5.3 四项）
- [ ] 字体自托管子集 + `document.fonts.load`
- [ ] 图标 sprite（替换全部字形符号）
- [ ] 纸张颗粒改造为容器背景

**验收**：`grep` 无裸十六进制色值；字号种类 ≤ 7；离线首屏标题不降级；axe 对比度 0 违规。

### P1 · 框架骨架（5 人日）

- [ ] Vite + Vue3 + TS + Pinia + router(hash) 接入 `/next`
- [ ] `api/client.ts`（超时/取消/重试/解包）+ 全量 TS 类型
- [ ] UI 原子组件（Button/Panel/Disclosure/Pill/Field/Toast/Modal/Drawer/Skeleton/Empty/Icon）
- [ ] 五视图空壳 + 导航
- [ ] 会话恢复与模型配置读取打通

**验收**：五视图可切换；旧版与新版并行；`/session/state` 数据正确渲染到导航与模型 chips。

### P2 · 主对话（8–10 人日）

- [ ] `Turn` 模型 + 阶段归属算法（§7.3）
- [ ] `TurnTrace`（进行中/完成两态 + 结构化详情）
- [ ] 增量流式渲染（§8.1）
- [ ] 回复分段与建议报告卡
- [ ] `CitationChip` + 引用解析
- [ ] `ThreadRail` 折叠/展开 + 引导链分组 + 历史归档
- [ ] 智能贴底 + 回到最新
- [ ] 停止生成
- [ ] 显式结束引导

**验收**：
- 发送后 1s 内可见阶段递进（本地模型慢时段落也应有 `classify_intent`）
- 5000 字回复流式渲染无卡顿、选区不被打断
- 30 轮对话可从 rail 一步定位任意轮
- 用户上翻时不被打断，出现"回到最新"

### P3 · 图谱（8–10 人日）

- [ ] 引擎分层（engine/physics/renderer/interaction/layout/theme）
- [ ] 自动停帧 + 预计算 + Barnes-Hut
- [ ] pointer/触摸/缩放/平移
- [ ] 聚焦高亮（邻接保留，其余淡出）
- [ ] 形状编码 + 曲线连线 + 标签避让
- [ ] 推理链单独成径
- [ ] `NodeInspector` 侧滑 + 双向联动
- [ ] 无障碍等价列表 + 键盘操作

**验收**：
- ≤60 节点 ≥55fps，静止 2s 自动停帧（Performance 面板可证）
- 视图切走后无 RAF 残留
- iPad 可拖拽与缩放
- hover 节点时邻接高亮、其余淡出
- 键盘可遍历节点并打开 Inspector
- 屏幕阅读器可读出图谱摘要

### P4 · 编辑页（5–7 人日）

- [ ] CodeMirror 6 + Markdown 预览
- [ ] 自动草稿 + 元信息条 + 快捷键 + 专注模式
- [ ] Weekly 三段卡片化 + 完成度
- [ ] `PickFromChat` 从对话摘取
- [ ] 保存前 md 预览 + 覆盖警告
- [ ] 保存后引导预处理
- [ ] 模型抽屉（对齐现有能力）

**验收**：对话片段一键落入周记；保存 → 预处理 → 检索可命中的闭环走通；刷新不丢草稿。

### P5 · 记录页 + 检索调试（5–7 人日）

- [ ] 筛选面板重构 + 已选 chips
- [ ] 命中高亮（转义安全）
- [ ] 三态空态
- [ ] 虚拟滚动
- [ ] `RankShiftChart` 排名迁移图 + 等价表格
- [ ] 双阶段 diff
- [ ] 参数预设
- [ ] 开关键盘可用

**验收**：一图可回答"重排是否有效"；筛选 30 条无串行延迟；键盘可操作全部开关。

### P6 · 收尾（3–4 人日）

- [ ] ARIA 全量基线（§14.2）
- [ ] `prefers-reduced-motion` 全局
- [ ] 破坏性操作统一确认（clear vs reset 文案区分）
- [ ] `trace` 与 `rd-log` 组件合并
- [ ] 删除冗余 CSS/DOM，清理死代码
- [ ] 性能基准测试（§15.1）
- [ ] 切换根挂载，`legacy/` 归档

**验收**：axe 0 serious/critical；Tab 遍历无焦点消失；Lighthouse Performance ≥ 90。

**合计约 37–46 人日（单人 7–9 周）。**

### 17.9 P0 实施记录（已完成 · 2026-11-07）

**已交付**

| 项 | 落点 |
|---|---|
| 三层设计令牌 | `web/src/styles/tokens.css`（base → role；7 级字阶 / 8 级间距 / 4 档圆角 / 4 级阴影 / 6 级 z-index） |
| 基础与工具层 | `base.css`（reset、焦点环、滚动条、reduced-motion）、`utilities.css` |
| 组件原子样式 | `components.css`（按钮 4 变体 + loading、图标按钮、面板、徽章、表单、应用外壳） |
| 自托管字体 | `styles/fonts.css` + `@fontsource-variable`（CJK 可变字体）+ 度量对齐 fallback 族 |
| 字体就绪信号 | `core/fonts.ts` → `fontsReady()`，供 Canvas 绘制前 await |
| 图标 sprite | `assets/icons.svg`（39 symbol / 24×24 / stroke 1.6）+ `AppIcon.vue` + `icon-names.ts` 类型约束 |
| 纸张质感 | `assets/paper-noise.svg` 作 `.app-shell` 背景（替代原全屏 `mix-blend-mode` 覆盖层） |
| 项目骨架 | Vite + Vue3 + TS(strict) + Pinia + hash 路由；五视图骨架 + 导航 + 视图头 |
| 后端并行挂载 | `main.py`：`/next` → `web/dist`，`/` → `web/legacy`，含 `/next` → `/next/` 重定向 |
| 旧版归档 | `web/legacy/`（`git mv` 保留历史） |

**实测验收（Playwright / Chromium 1440×900）**

| 项 | 结果 |
|---|---|
| 首屏关键 CSS | **4.06 KB**（gzip），预算 40KB ✅ |
| 首屏 JS | **44.6 KB**（vendor 39.4 + app 5.2，gzip），预算 180KB ✅ |
| 字体 CSS | 独立 chunk 92.8 KB，异步加载、单独缓存（不进关键路径） |
| 三款字体真实生效 | Fraunces / Noto Serif SC Variable / Noto Sans SC Variable 均 `status=loaded` ✅ |
| 图标解析 | 39 symbols、7 uses、7 resolved，首个图标渲染 19×19 ✅ |
| 导航与路由 | 五视图 hash 路由、`document.title`、`aria-current` 全部正确 ✅ |
| 焦点环 | Tab 遍历 6 个可聚焦元素，`--focus-ring` 全部可见 ✅ |
| 对比度 | 8 项核心组合全部 ≥4.5:1（最低 4.59:1，主按钮）✅ |
| 控制台错误 / 失败请求 | 0 / 0 ✅ |

**与设计的偏差（需知悉）**

1. **CSS 预算拆分为「关键 CSS ≤40KB + 字体 CSS 独立」**。CJK 的 unicode-range 分片必然产生 200+ 条 `@font-face`（232KB / gzip 93KB），这是分片机制固有成本，Google Fonts 的 Noto 系列同样如此。处理：`fonts.css` 由 `core/fonts.ts` 动态 import，Vite 拆为独立 CSS chunk，不阻塞首屏；加载期间由度量对齐的 `*Fallback` 族承接，无空白文字。
2. **CJK 改用可变字体包**（`@fontsource-variable/*`）而非静态多字重包。静态包每字重独立分片，400/500/700 三档会让传输量翻三倍；可变字体单分片覆盖 200–900 区间，101 个 woff2 覆盖全集。
3. **`base` 路径可配置**（`VITE_BASE`，默认 `/next/`）。切换根挂载时用 `VITE_BASE=/` 重新构建。

**遗留（P0 未覆盖）**

- 图标 39 个，P2–P5 出现新语义时需同步补 symbol 与 `ICON_NAMES`。
- `web/scripts/verify-*.cjs`、`check-contrast.cjs` 为本次验证脚本，建议保留为回归基线，P6 统一整理为 `npm run verify`。
- 窄屏（<1100px）自动折叠已实现；320px 极窄档与底部 tab bar 留到 P6。
- 深色「夜读」主题令牌分支未建（§19-1 待决）。

### 17.10 P1 实施记录（已完成 · 2026-11-07）

**已交付**

| 项 | 落点 |
|---|---|
| API 客户端 | `core/api/client.ts`：解包 `code`、超时（`ApiTimeoutError`）、外部取消（`AbortController`）、5xx 指数退避重试（400/取消/超时不重试）、`createRequestScope()` 视图级取消域 |
| 接口类型 | `core/api/types.ts`：严格对应后端 DTO（Document / Memory / SessionState / TraceItem / GraphData / RetrievalDebugResp 等） |
| API 模块 | `core/api/index.ts`：按域分组（session / chat / model / data / search / tool / retrieval），带超时策略 |
| SSE 客户端 | `core/stream/trace-stream.ts`：EventSource + 3 次重连后降级轮询；**不按 version 重置**（§1.7） |
| UI 原子组件 | Button / Panel / Disclosure / Pill / Field / Skeleton / Empty / Modal / Drawer / Confirm / Toast / Icon |
| 浮层行为 | `useOverlay.ts`：焦点陷阱 + Esc + body 滚动锁 + 焦点归还，Modal/Drawer 共用 |
| Stores | session / models / trace / records / write / ui |
| 视图实装 | Trace（SSE 实时）、Records（筛选+检索）、Write（草稿+双模式）三个视图已达 P1 可用水平；Chat 与 Retrieval 保留骨架 |

**实测验收（Playwright / Chromium 1440×900）**

| 项 | 结果 |
|---|---|
| 五视图渲染 | 标题、导航激活态、`document.title` 全部正确 ✅ |
| 控制台错误 / 失败请求 | 0 / 0 ✅ |
| 横向滚动 | 五视图均无；窄屏（900px）侧栏收窄至 72px 且无溢出 ✅ |
| 焦点陷阱 | 确认弹窗内 Tab 循环 5 次全部留在浮层内 ✅ |
| Esc 关闭 + 焦点归还 | 关闭后焦点回到触发按钮 ✅ |
| body 滚动锁 | 浮层打开时 `position: fixed`，关闭后还原 ✅ |
| 表单可聚焦 | 模型抽屉 5 select + 3 input，**0 个被 `display:none` 隐藏**（原项目缺陷）✅ |
| Toast 无障碍 | `role="status"` + `aria-live="polite"` ✅ |
| 真实数据打通 | 模型 chips 显示后端实际配置（deepseek-flash）；记录页加载 31 篇真实文档；主题筛选 31→14 条 ✅ |
| 检索守卫 | 精准文本模式未填原文时拦截并提示 ✅ |
| 草稿持久化 | 输入 → 2s 防抖落盘 → **切换视图再回来草稿完整保留** ✅ |
| `AppDisclosure` | ARIA 正确（`aria-expanded` / `aria-controls`）、鼠标与键盘均可切换、caret 旋转 ✅ |
| SSE 实时性 | 后端新增 trace 后列表由 4 条实时增至 6 条 ✅ |

**P1 期间发现并修复的缺陷**

1. **WriteView 卸载时误删草稿**：`onBeforeUnmount` 注释写的是「强制落盘」，实际调用 `clearDraft()`，导致切换视图丢失未保存内容。已改为 `persistDraft()` 并在 store 中暴露该方法。
2. **RecordsView tab 切换残留上一 tab 的计数**：切到「历史记忆」时计数仍显示文档检索的 14 条，误导用户。已改为始终回落到目标 tab 的全量列表。
3. **Vite 把字体 CSS 合并进主 bundle**：CJK 分片 200+ 条 `@font-face` 一度让主 CSS 达 252KB。改为 `core/fonts.ts` 动态 import，拆为独立 chunk。
4. **`/next` 无尾斜杠 404**：`StaticFiles` 挂子路径不自动重定向，已在 `main.py` 显式处理。

**当前依赖（gzip）**

- 首屏关键 CSS **4.35 KB**、JS **44.6 KB**（vendor 39.4 + app 8.3）
- 字体 CSS 独立 chunk，异步加载

**遗留（P1 未覆盖）**

- Chat 与 Retrieval 仍是骨架占位（分别在 P2 / P5）。
- Write 未接 CodeMirror（当前为 textarea + 字符统计 + 草稿，P4 升级）。
- Records 结果卡未渲染（只显示条数，P5 补齐 `ResultCard` + 命中高亮）。
- 视图级取消域只在 Records 接入了 `createRequestScope()`，其余视图在 P2/P5 接入。

### 17.11 P2 实施记录（已完成 · 2026-11-08）

**已交付**

| 项 | 落点 |
|---|---|
| Turn 领域模型 | `core/domain/turns.ts`：Turn 聚合、阶段追加、定稿、耗时、历史还原、引用归集 |
| 阶段语义映射 | `core/domain/stages.ts`：10 个已知 stage + **未知阶段兜底**；结构化摘要提取（memory_count / principle_count / evidence_status / remediation 等） |
| 引用解析 | `core/domain/citations.ts`：`[[cite:]]` / `[[guide:]]` 双类型双查（文档+记忆+图谱节点）、按首次出现编号、建议报告分段、流式 token 化（含跨 chunk 半标记处理） |
| 流式客户端 | `core/stream/chat-stream.ts`：fetch + ReadableStream、**CRLF/LF 兼容分帧**、AbortSignal 取消 |
| Turn store | `stores/turn.ts`：三条流汇聚、阶段归属、发送/中止/结束引导 |
| TurnTrace | `components/chat/TurnTrace.vue`：进行中/完成两态、时间轴、真实阶段耗时、结构化明细、警示与错误 |
| ChatMessage | `components/chat/ChatMessage.vue`：气泡、增量 token 渲染、建议报告卡、流式光标、操作栏 |
| CitationChip | `components/chat/CitationChip.vue`：类型色 + 图标 + 序号 |
| ChatComposer | `components/chat/ChatComposer.vue`：模式选择/锁定条、显式结束引导、停止生成、自动增高 |
| ThreadRail | `components/chat/ThreadRail.vue`：折叠刻度轨（形状编码）+ 展开大纲（引导链分组/筛选/视口高亮） |
| ChatView | 组装 + 智能贴底 + 「回到最新」+ IntersectionObserver 定位 + 跳转脉冲 |

**实测验收（真实对话，非模拟）**

直接咨询（单轮）：

| 项 | 实测值 |
|---|---|
| 等待期进度感 | 发送后即出现 TurnTrace「正在处理 1 步」，正文位置显示等待点 |
| 阶段递进 | 唤起记忆 **15.0s** → 检索结果 939ms（3 原则 · 0 经历）→ 生成回复 **16.9s** → 生成完成 16ms → 保存会话 10ms |
| 整轮耗时 | **34.1s**（旧版这 34 秒是纯白屏） |
| 正文 | 1793 字，增量渲染无卡顿 |
| 引用 | 8 个 chip，类型着色（文档=墨绿），内联不打断阅读 |
| 中止 | 发送中显示「停止」按钮 |

引导咨询（两轮）：

| 项 | 实测值 |
|---|---|
| 模式锁定条 | 「引导咨询」徽章 + 锚定问题 + 「第 1 问」+ 结束按钮 |
| 引导者身份 | 紫头像、`.msg--guide`、推理 chip（`cite--reason`） |
| 输入占位符 | 切换为「回答引导者的问题…」 |
| 显式结束 | 点「结束并生成建议」→ 第二轮完成 |
| **建议报告卡** | 成功渲染（`.msg__advice`，标题「建议总结」） |
| ThreadRail | 2 个刻度，其中报告轮次标记为 `mark--report` |

**P2 期间发现并修复的 4 个缺陷**

1. **SSE 分帧按 `\n\n` 切，但 sse_starlette 实际输出 CRLF** —— 一帧都切不出来，正文完全收不到，界面却"看起来在跑"。这是最严重的一个：静默失败。已改为 `findFrameBoundary()` 兼容 `\r\n\r\n` 与 `\n\n`，并补 9 个单测。
2. **Vue 响应式丢失**：`turn` 原始对象 push 进 `ref([])` 后，回调仍操作原始引用，Vue 追踪不到，导致界面卡在「正在处理」而正文其实已到 1793 字。改为 push 后取回数组元素（代理）再传给回调。
3. **历史回合耗时显示「29901124m21s」**：历史消息 `startedAt = 0` 是哨兵，`Date.now() - 0` 算出天文数字。`turnDuration()` 对 `<= 0` 返回 `null`，UI 按存在性渲染。
4. **模式锁定条不出现**：后端首条锁定模式后本地 `session.mode` 未刷新，`modeLocked` 恒为 false，「结束并生成建议」按钮永不出现。发送后补一次 `session.load()`。

**新增单测（27 个，全部通过）**

```
node scripts/test-sse-frames.mjs    # 9 个：CRLF/LF、任意分包、多行 data、畸形 JSON、空帧、末帧兜底
node scripts/test-turns.mjs         # 8 个：耗时哨兵回归、残留过滤、签名一致性
node scripts/test-citations.mjs     # 10 个：建议报告分段、引用 token 化、跨 chunk 半标记、截断标记丢弃
```

**遗留（P2 未覆盖）**

- 「摘入周记」只写入 store 不跳转（用户体验待 P4 编辑页完成后打磨）。
- 一键总结用的是 `session.load()` 而非 `/tool/summarize`（P5 修正）。
- 流式渲染是「累积文本 + 每帧 token 化」，尚未做真正的 DOM 增量追加；当前 5000 字以内无感知问题，超长回复再优化。
- ChatView 未接 `createRequestScope()`（发送走 streamChat 自带 AbortController，其余请求量小）。

### 17.12 P3 实施记录 + 主对话增强（已完成 · 2026-11-08）

#### A. 主对话增强（用户提出）

**1. 富文本解析（Markdown-lite）** — `core/domain/richtext.ts` + `components/chat/RichText.vue`

支持：`**加粗**`、`*斜体*`、`` `行内代码` ``、`「」衬线强调`、标题、有序/无序列表、引用块、代码块。

三个设计决策：

| 决策 | 理由 |
|---|---|
| **自己写而非 markdown-it** | 需与 `[[cite:]]` 共存（引用要渲染成交互 chip）、流式要处理半个标记、输出节点树而非 HTML 串 |
| **全程 VNode，不碰 innerHTML/v-html** | 文本一律作为文本节点渲染，模型输出里的 `<script>` 只会显示为字面量。**从根本上杜绝 XSS** |
| **「」→ `<q class="rt__quote">` 衬线字体** | 中文语境里「」常用于强调关键短语，换衬线字体 + 朱砂色能形成纸感排版的呼吸感，比加粗更克制 |

流式处理：`parseInline(text, isFinal)` 在非最终状态下把尾部未闭合标记（`**未完` / `[[cite:ab` / 单个 `*`）放进 `blockedTail` 暂存，避免闪烁；`isFinal` 时若仍未闭合则判定为模型输出截断，直接丢弃残片而不是把 `[[cite:ab` 展示给用户。

**2. 执行链（头像下方）** — `components/chat/ExecutionChain.vue`

设计上分两层，避免撑高气泡：

- **常驻摘要行**（一行）：`✓ 唤起记忆 · 检索知识 · 保存会话  [3] 38.6s ▾`
- **展开详情**：7 个阶段各有真实耗时，竖线时间轴串联，警示阶段用琥珀色

摘要按阶段语义拼接（classify→理解意图、retrieve→检索知识…），引用数来自阶段详情里累积的 `docIds` 去重。

**重要**：原 `TurnTrace.vue` 已删除——它的职责被执行链完全覆盖，保留会造成两套并行的阶段展示逻辑。

**3. 引用 chip 升级**：点击 → 在图谱中选中该节点并打开 Inspector；hover → 图谱对应节点脉冲高亮（双向联动）。

#### B. P3 图谱引擎

**模块划分**（`core/graph/`，完全不依赖 Vue）：

| 文件 | 职责 |
|---|---|
| `physics.ts` | 力模型、Barnes-Hut 四叉树、按关系类型区分弹簧长度、按类型分层初始化 |
| `renderer.ts` | 分层绘制（静态网格层 + 动态层）、形状编码、贝塞尔连线、聚焦淡出 |
| `engine.ts` | 生命周期、自动停帧、viewport（缩放/平移）、pointer 交互 |
| `theme.ts` | 从 CSS 变量读色值，消除 JS/CSS 双份真相 |

**四个关键改进（对应旧版缺陷）**：

| 旧版问题 | 新版做法 |
|---|---|
| RAF 永不停机，视图切走仍在跑 | 平均位移 < 0.35px/帧持续 20 帧即 `stop()`；任何交互 `wake()` 重启 |
| 每帧两次 O(n²)（斥力 + draw 内 filter 计数） | 度数在 `setData` 预计算；≥80 节点启用 Barnes-Hut（θ=0.9） |
| 仅鼠标事件，触屏不可用 | 统一 pointer 事件 + `touch-action: none` + `setPointerCapture` |
| hover 只放大自身，不表达「关联」 | 邻接保留 opacity=1，其余淡出至 0.12，相关连线加粗到 2.2 |

**视觉设计**：
- 形状编码（不只靠颜色，兼顾色盲）：会话=双层光环圆、记忆=实心圆、文档=圆角方、推理=菱形
- 连线曲线化（二次贝塞尔，沿法线偏转，同源边方向一致以减少交叉）
- 标签描边底（`strokeText` + `fillText`），压在连线/网格上仍可读

**无障碍**：
- `role="img"` + 动态 `aria-label`：「会话关联图谱：1 个会话、3 篇文档、1 步推理」
- 可折叠的 DOM 等价列表（5-6 个节点，可点击打开 Inspector）
- 画布 `tabindex="0"`，`:focus-visible` 描边

**NodeInspector**：右侧侧滑（非居中模态，避免遮住图谱），显示类型/标题/摘要/来源/邻接节点/**引用此节点的对话轮次**（可点击跳回）。

#### C. 实测验收

**自动停帧（设计文档 §10.3 的核心要求）**

| 项 | 结果 |
|---|---|
| 静止后画布像素稳定 | ✅ 三次哈希完全一致 |
| 交互后重新唤醒 | ✅ 拖拽后继续演化 |
| 交互后再次停帧 | ✅ 稳定后画布不再变化 |
| **切走视图后残留 RAF** | **0 个**（旧版永不停机） |

> 注：初次用「3 秒内 RAF 调用次数」测量时得到 180 次，误判为停帧失效。实际是探针自身递归调用 RAF 污染了统计。改用「画布像素哈希是否变化」+「拦截 RAF 记录调用栈」确认：图谱确已停帧，`activeRafSources` 为空。

**新对话执行链（真实数据）**

```
✓ 唤起记忆 · 检索知识 · 保存会话   [3] 38.6s
  唤起记忆   匹配 0 条相似记忆            23.7s
  补充检索   扩大召回名额重检                0ms
  检索结果   3 原则 · 0 经历              901ms
  生成回复   处理中                      12.8s
  生成完成   3 原则 · 0 经历                 0ms
  校验证据   证据偏弱                      15ms
  保存会话   2 轮对话 · 提及 3 篇文档        3ms
```

**其他**

| 项 | 结果 |
|---|---|
| 图谱绘制 | 327×606 画布，296 个非空像素采样 |
| 缩放控件 / 滚轮 / 拖拽平移 | 100% → 125% → 112%，均生效 |
| 聚焦过滤（会话/记忆/文档/推理） | 切换生效 |
| Inspector | 类型/标题/摘要/邻接 4 个全部正确，可关闭 |
| 「」衬线强调 | 真实回复中渲染 5 处 |
| 原始标记泄漏（`**` / `[[cite:`） | **0** |

#### D. 期间发现并修复的问题

1. **`remediation` 阶段无映射** —— 显示为原始 `remediation` / `remediation`。根因是我早期 grep 只看了 `registry.py` / `executor.py`，漏了 `remediation.py`。
   **修复**：补全映射，并从后端源码提取全部 **27 个 stage** 建立覆盖测试（`test-stages.mjs`）——以后后端新增阶段，测试会直接报出未映射项。
2. **`evaluate` 的 `weak` / `gap` 原样输出** —— 改为可读化（证据充分/偏弱/不足）。
3. **停帧阈值按总位移判断** —— 6 个节点每个飘 0.06px 就超过 0.35 阈值，永远停不下来。改为**平均位移**。
4. **历史回合展开执行链是空白** —— `turnsFromHistory` 不重建 stages，展开后无内容。改为无阶段时隐藏展开箭头与 `aria-expanded`，且 hover 无反馈（不暗示可点）。
5. **Inspector 点击画布中心命中失败** —— `zoomToFit()` 后节点位置与画布中心不一致。测试改用无障碍列表作为可靠入口（同时也验证了该列表可用）。
6. **嵌套斜体解析失败** —— `*斜*` 被最小长度守卫 `end - i > 2` 拒绝。改为只要求定界符间有内容。

#### E. 单测（58 个，全部通过）

```
test-richtext.mjs         15 个  加粗/斜体/代码/「」/嵌套/引用共存/流式半标记/截断处理
test-richtext-render.mjs   7 个  块级结构；数字开头与加粗开头不被误判为列表
test-stages.mjs            9 个  27 个后端 stage 全覆盖；关键阶段必须有正经标题
test-citations.mjs        10 个  报告分段、引用 token 化、跨 chunk 半标记
test-turns.mjs             8 个  耗时哨兵回归、残留过滤、签名一致性
test-sse-frames.mjs        9 个  CRLF/LF、任意分包、畸形 JSON、空帧、末帧兜底
```

#### F. 遗留

- 图谱窄屏（<1100px）直接隐藏，P6 补抽屉形态。
- 推理链目前混在关联网络中渲染，§10.5 设想的「单独成径」未做。
- 云图标签避让（8 方向候选位）未实现，节点密集时标签可能重叠。
- 富文本未支持表格与嵌套列表。后端 prompt 不要求输出这些结构，暂不做。

### 17.13 P5 实施记录（已完成 · 2026-11-08）

#### A. 排名迁移图（本阶段核心增量）

**问题**：检索调试原有四个折叠面板，要回答「重排到底有没有用」必须人肉在各阶段间比对同一文档的位次。

**方案**：Canvas 斜率图，一张图看清位次流动。

**数据模型**（`core/retrieval/rank-shift.ts`，纯函数、与绘制分离、可单测）：

- **列** = 有排名输出的阶段（按 `enabled_pipeline` 顺序）+ `final`
- **行** = 所有出现过的 `doc_id` 并集
- **点** = 该文档在该阶段的 `rank` 与 `score`
- **三态判定**：
  - `final` — 出现在 `final.doc_ids` 里
  - `appeared` — 首次出现不在第 0 列（后期由某条召回链路引入）
  - `dropped` — 首列命中但未进最终
- **排序**：进入最终的置顶并按最终位次排列，其余按首次出现列与位次

**视觉编码**：
| 元素 | 含义 |
|---|---|
| 朱红粗线 | 进入最终结果 |
| 墨绿细线 | 后期召回（起点标空心 `+`） |
| 灰色细线 | 被淘汰 |
| 贝塞尔曲线 | 让位次转折呈现「流动」而非折线图的生硬感 |
| 列头数字 | 该阶段候选数 |
| hover 某节点 | 该轨迹加粗、其余淡出至 0.14 —— 从密集交叉中分离单条路径 |

**无障碍**：`role="img"` + 动态 `aria-label`（"21 篇文档跨 5 个阶段的位次变化，其中 3 篇进入最终结果"）；可折叠等价表格（列 × 行完整位次）；屏幕阅读器纯文本摘要。

#### B. 记录页结果卡

- **命中高亮**（`HighlightText.vue`）：**先切分文本再逐段创建文本节点**，全程 VNode。不用「拼 HTML 再塞 mark」——那样用户数据里的 `<` `>` 会变成标签。
- 关键词按长度降序匹配，避免短词抢先破坏长词
- 卡片骨架：标题 + 类型徽章 + 日期 + 摘要（高亮）+ 主题/关键词/情绪 chips + 可展开详情
- 详情按类型切换：文档（正文 / problem-analysis-solution / 来源路径）、记忆（洞察 / 引用文档 / 对话记录气泡）
- **动作**：「在对话中追问」→ 跳转对话页；「摘入周记」→ 写入 weekly store

#### C. 检索调试页

链路开关（`aria-pressed`，键盘可用）→ 参数（每项带 hint）→ prompt（Ctrl/⌘+Enter 运行）→ 排名迁移图 → 最终结果 → 逐阶段候选 → 查询改写 + 日志 → 全部文档浏览。

参数默认值优先取 `/retrieval/meta`，用户改过之后不再被覆盖（`paramsTouched` 语义，与后端契约一致）。

#### D. 实测验收

**检索调试（真实运行）**

| 项 | 结果 |
|---|---|
| 运行耗时 | 14.41s |
| 最终条数 | 3 |
| 阶段面板 | 5 个 |
| 日志条目 | 8 条 |
| 排名迁移图 | 21 篇文档跨 **5** 阶段，843 个非空像素采样 |
| 等价表格 | 21 行 |
| 查询改写 | "总是内耗该如何与自己和解，重建内在的自我接纳" |
| hover 命中 | ✅ 光标变 pointer，轨迹高亮 |
| 文档浏览 | 31 篇 |

**记录页**

| 项 | 结果 |
|---|---|
| 初始渲染 | 31 张卡，413 个 chips |
| 搜索「掌控感」 | 1 条，**23 处高亮命中** |
| 展开详情 | 正文 / 动作按钮齐全 |
| 「在对话中追问」 | 跳转 `#/` ✅ |

#### E. 期间发现并修复的问题

1. **排名迁移图出现空列** —— 「查询改写」（`optimize_prompt`）只产出文本、无候选排名，却占了一列，让位次图出现无意义断点。改为**只保留有 results 的阶段作为列**。
2. **最终结果标题被裁切** —— 右留白写死 120px，中文标题 13 字可达 ~150px。改为按 `ctx.measureText` 实测最长标题动态计算，上限为画布宽度的 34%。
3. **验证时误判「搜索返回 0 条」** —— 用「内耗, 焦虑」搜索得到 0，一度怀疑参数传递有误。逐层排查（DB → `meta_filter` → HTTP API）后确认：**是 bash 里 curl 传中文时编码损坏**，用 urllib 显式 UTF-8 编码测试返回正常 1 条；且该数据集里本就没有"内耗"这个词。改用数据中真实存在的「掌控感」验证通过。

> 这一条值得记下来：排查时先验证了「DB 层能否命中」，再验证「函数层」，最后验证「HTTP 层」，三层分别给出 1 / 1 / 0，立刻把问题定位到传输编码而非业务逻辑。分层验证比直接改代码高效得多。

#### F. 单测（70 个，全部通过）

新增 `test-rank-shift.mjs`（12 个）：列构建、三态判定、排序、空数据、缺失 rank 兜底、后期召回识别。

```
test-richtext        15   test-citations      10   test-stages        9
test-richtext-render  7   test-turns           8   test-rank-shift   12
test-sse-frames       9   —— 合计 70
```

#### G. 遗留

- 检索调试未实现「双阶段 diff」与「参数预设保存」。
- 记录页筛选区在 ≥1280px 未做成左侧固定栏（当前为顶部表单）。

### 17.14 P4 实施记录（已完成 · 2026-11-08）

#### A. CodeMirror 6 编辑器

**选型理由**：textarea 在长文本下中文输入法（IME）组合输入有兼容问题，且无法做语法高亮。CodeMirror 的 IME 处理成熟，分包后 172.8KB gzip，**只在进入编辑页时加载**，不影响首屏。

**v-model 双向同步的关键**：用 `lastEmitted` 记录自己最后一次发出的值，外部 watch 到相同值就跳过——否则会陷入「改 → 重置文档 → 触发 change → 再改」的循环。

**与设计系统对齐**：主题从 CSS 变量读取，光标/选区/activeLine/placeholder 全部用令牌色，与整站纸感一致；Markdown 语法高亮用 `HighlightStyle` 手写，标题加粗、引用斜体、列表用朱砂色。

**快捷键**：`Mod-s` 保存、`Mod-Enter` 保存并进入后续流程、`indentWithTab`、完整 history 撤销栈。

#### B. 从对话摘取（产品闭环的关键一环）

这是本产品最独特的能力：**把一次咨询沉淀成可被检索的周记原则**。

- 候选来源：每轮对话的「建议报告」（优先）与「对话轮次」
- 插入目标：problem / analysis / solution 三段任选
- 插入格式：`> 来自对话第 N 轮的建议总结` + `> ` 引用块，保留出处
- 插入后自动切到 Weekly 模式

**发现并修复的缺陷**：`PickFromChat` 原本只读 `turnStore.turns`，而 `hydrate()` 只在 ChatView 的 `onMounted` 调用——**用户直接从编辑页进入时列表是空的**。改为在面板挂载与每次打开时都 `hydrate()`，保证任何入口都能摘取。

#### C. 编辑页增强

| 能力 | 说明 |
|---|---|
| 专注模式 | 隐藏头部与侧栏，单栏 `68ch` 居中最优行宽 |
| 预览 | 用与对话一致的 `RichText` 渲染保存后的完整 Markdown（含标题结构） |
| 覆盖警告 | 检测同名文件时状态条提示 + 保存二次确认（后端 `open(w)` 直写，无版本） |
| 保存后联动 | Toast 直接带「立即预处理」动作按钮，一步进入知识库 |
| 实时状态 | 字数 / 阅读时长 / 草稿保存时刻 / Weekly 完成度 3/3 |

#### D. 实测验收

| 项 | 结果 |
|---|---|
| CodeMirror 挂载 | 行号、contenteditable、语法高亮均正常 |
| 输入同步 | 输入 20 字 → 状态条实时显示「20 字」 |
| 草稿自动保存 | 2s 防抖落盘，状态条显示保存时刻 |
| Weekly 三编辑器 | problem / analysis / solution 各一个独立编辑器 |
| 从对话摘取 | 1 个候选、3 个目标段落 |
| **插入到 solution** | 完成度 **0/3 → 1/3**，状态变「已填写」 |
| 预览 | 4 个标题，1323 字，`RichText` 渲染 |
| 专注模式 | 头部隐藏、单栏收窄 |
| **保存落盘** | `E2E-验证-*.md` 写入 `data/notes/Weekly_thoughts/`，格式与后端约定一致 |
| 保存后 Toast | 含「立即预处理」动作按钮 |
| 预处理 | 成功，文档数不变（增量模式，无新文件时正确） |

#### E. 发现并修复的重要后端缺陷

**`/tool/preprocess` 返回 `null`** —— `api_preprocess()` 函数**完全没有 return 语句**，Python 隐式返回 `None`，FastAPI 序列化成 JSON `null`。前端按统一响应体解包 `{code,msg,data}`，读到 `null.code` 直接崩溃，功能完全不可用。

排查路径：前端 Toast 显示 `Cannot read properties of null (reading 'code')` → 直接 curl 该端点确认返回字面量 `null` → 读 `api/tool.py` 末尾发现无 return。

**两边都修**：
1. 后端补 `return resp(CODE_OK, "预处理完成", data={...})`
2. 前端 `client.ts` 增加防御：响应体不是对象时抛出可读错误 `响应格式异常（HTTP xxx）：响应体不是统一结构`，而不是让调用方拿到 `null.code` 崩溃

这一条值得记：**统一响应体的契约必须双向守住**。后端漏写 return 是根源，但前端不该因为单个端点的疏漏就整块功能不可用。

#### F. 构建产物体积（分包效果）

| chunk | gzip | 何时加载 |
|---|---|---|
| vendor | 46.2 KB | 首屏 |
| index | 8.6 KB | 首屏 |
| index.css | 4.2 KB | 首屏 |
| ChatView | 17.9 KB | 进主对话 |
| RetrievalView | 9.9 KB | 进检索调试 |
| WriteView | 6.4 KB | 进编辑页 |
| **editor（CodeMirror）** | **172.8 KB** | **仅进编辑页** |
| fonts.css | 92.8 KB | 异步，单独缓存 |

首屏关键路径 = vendor + index + index.css ≈ **59 KB gzip**，远低于 180KB 预算。

#### G. 遗留

- 编辑页未做 Markdown 工具栏（加粗/列表按钮）——快捷键与语法高亮已足够，且工具栏会挤压写作空间。
- 「从对话摘取」未支持跨会话的历史记忆（只能摘当前会话；归档记忆需 `/memory/all`）。

### 17.15 P6 实施记录（已完成 · 2026-11-08）—— 重构收尾

#### A. 无障碍：从 8 处严重违规到 0

用 `@axe-core/playwright` 对五视图做 WCAG 2.1 AA 全量扫描，首轮结果：

| 视图 | 违规 | 级别 |
|---|---|---|
| 过往记录 | `aria-required-children` | critical |
| 过往记录 | `label` × 2（日期输入） | critical |
| 过往记录 | `select-name` | critical |
| 码字编辑 | `aria-input-field-name`（CodeMirror） | serious |
| 码字编辑 | `aria-prohibited-attr`（宿主 div 上的 aria-label） | serious |
| 码字编辑 | `label` | critical |
| 检索调试 | `label` × 3（参数输入） | critical |
| 检索调试 | `select-name` | critical |

**根因是一个设计缺陷**：`AppField` 用 `useId()` 生成 id 并通过 slot 传给使用方，但**实际没有任何一处把它绑到控件上**。等于表单字段在设计上就没有可访问名称。

**修复方式**（拒绝「要求每个调用方自觉传 id」这种不可靠方案）：

`AppField` 挂载后自动扫描内部的原生控件（`input` / `select` / `textarea`），按需设置：
- `aria-labelledby` → 关联 label 的 id
- `aria-describedby` → 关联 hint / 错误信息
- `aria-invalid` / `aria-required` → 状态语义

项目里所有控件都是原生标签，这个方案覆盖面 100%，且**使用方无需做任何事**。

其余三处：
- `role="tablist"` → 改 `role="group"`。标签页语义要求子元素为 `role="tab"` 且配套 `tabpanel`，这里是「两个互斥的视图切换按钮」，用 tablist 是错的。
- CodeMirror 的可访问名挂到 `.cm-content`（`role=textbox`）上，用 `EditorView.contentAttributes` 注入，而不是挂在宿主 div（无 role 的 div 不允许 `aria-label`）。
- 文档过滤区的 `select` 不在 `AppField` 内，补 `aria-label`。

**最终结果：五视图 × WCAG 2.1 AA = 0 violations**。

#### B. 死代码清理

| 删除项 | 原因 |
|---|---|
| `AppPanel.vue` | 各视图都用了自己的 scoped 面板样式，组件从未被引用 |
| `useFieldA11y.ts` | 中途方案产物，被 `AppField` 自动关联替代 |
| `.c-panel` / `.c-badge` / `.c-chip` 样式块（1234 字符） | 对应的三个组件删除后成为孤儿样式 |

#### C. `prefers-reduced-motion` 运行时切换

图谱原本只在 `setData` 时读一次媒体查询。补上 `matchMedia('change')` 监听：**用户改系统设置后立刻生效，无需刷新**。切到减弱动效时，布局直接 `settle()` 到稳定态并停帧。

#### D. 根挂载切换（重构的最后一公里）

```python
# main.py
_frontend_dir = DIST_DIR if DIST_DIR.is_dir() else LEGACY_DIR
app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="web")
```

- `vite.config.ts` 的 `base` 默认值改为 `/`
- 新版 `web/dist` 成为根路径默认界面
- **dist 不存在时自动回退旧版**（刚 clone 仓库未构建的场景不会白屏）
- 旧版保留在 `web/legacy` 作为兜底

#### E. 最终验收

| 项 | 结果 |
|---|---|
| 五视图渲染 | 标题 / 导航激活态 / `document.title` 全部正确 |
| **axe 无障碍扫描** | **五视图 × WCAG 2.1 AA = 0 违规** |
| 键盘可达 | 7 个焦点元素，**全部有可见焦点环** |
| 横向滚动 | 五视图均无 |
| 控制台错误 / 失败请求 | 0 / 0 |
| 单元测试 | **70 个全绿** |
| 代码量 | 14,760 行 |

#### F. 重构总览（P0–P6 全部完成）

| 阶段 | 交付 | 关键成果 |
|---|---|---|
| P0 | 设计令牌 / 字体 / 图标 / 脚手架 | 首屏 CSS 4.2KB，字体自托管摆脱 CDN |
| P1 | API 客户端 / UI 原子组件 / 三个视图 | 焦点陷阱、Esc、滚动锁、Toast 无障碍 |
| P2 | Turn 模型 / TurnTrace / 流式 | **34 秒白屏变成可见的阶段进度** |
| P3 | 图谱引擎 / 富文本 / 执行链 | 自动停帧、Barnes-Hut、形状编码、Markdown-lite |
| P5 | 记录页 / 检索调试 / 排名迁移图 | **一图回答「重排有没有用」** |
| P4 | CodeMirror / 从对话摘取 | **咨询洞察沉淀为可检索原则** |
| P6 | 无障碍归零 / 根挂载 | axe 0 违规，新版成为默认界面 |

#### G. 遗留（后续可做的增强）

- 编辑页 Markdown 工具栏（当前快捷键已够用）
- 从对话摘取支持跨会话的归档记忆
- 检索调试的双阶段 diff 与参数预设
- 记录页 ≥1280px 的左侧固定筛选栏
- 图谱推理链「单独成径」（当前混在关联网络中）
- 深色「夜读」主题（令牌层已预留分支，未实现）
- 图谱窄屏抽屉形态（当前 <1100px 直接隐藏）

---

## 18. 需后端配合的契约变更

按优先级分级。**P0/P1 都不需要后端改动，可直接开工。**

### 18.1 建议（半天级，显著提升）

| 改动 | 位置 | 收益 |
|---|---|---|
| graph 节点补 `created_at` | `api/graph.py` | 入场动画可按时间错峰，而非随机半径 |
| `/session/state` 补 `guided_progress`（当前第几问） | `api/state.py` | 引导进度条不必从 `guided_reasons` 长度反推 |
| 新增 `GET /memory/{id}` | `api/memory.py` | 归档详情不必拉全量 `memory/all` |

### 18.2 推荐（1–2 人日，显著提升体验上限）

**`/chat/stream` 真流式化**

现状伪流式导致首字延迟 = 全量生成耗时。改造思路：

```python
# core/agent.py
def agent_service_entry(..., emit: Callable[[dict], None] | None = None):
    ...
# executor / tools 在关键点 emit：
emit({"type": "phase", "phase": "classify_intent", "label": "..."})
emit({"type": "phase", "phase": "tool_result", "data": {...}})

# api/chat.py
queue: asyncio.Queue = asyncio.Queue()
def emit_threadsafe(evt):
    loop.call_soon_threadsafe(queue.put_nowait, evt)

async def generator():
    task = loop.run_in_executor(None, agent_service_entry, ..., emit_threadsafe)
    while True:
        evt = await queue.get()
        if evt is _DONE: break
        yield {"data": json.dumps(evt, ensure_ascii=False)}
```

收益：
- 前端不再需要旁路推断阶段，TurnTrace 从"旁路推断"变"主路权威"。
- 多标签页不再互相串台（当前 `GLOBAL_TRACKER` 是全局的，两个标签页会看到对方的 trace）。
- 真正的 `reply_chunk` 可以来自 LLM 的 `stream=True`，首字延迟降到秒级。

**建议**：先用纯前端方案完成 P2，用真实体感再决定是否投入这个改动。

### 18.3 不建议现在做

**多会话支持**（`current_session` 单例改造）。

会牵动 `SESSION_STATE` 全局单例与锁，且与 `docs/agent_architecture_refactor_plan.md` 里"阶段 5 多会话"的计划冲突。当前"侧边定位先前对话"用会话内导航 + 归档记忆浏览已足够。

---

## 19. 待决事项

| # | 事项 | 建议 | 影响 |
|---|---|---|---|
| 1 | 是否需要深色「夜读」主题 | **建议做**。纸感配色天然适合暖棕暗色，用户夜间写日记是真实场景。令牌层已预留（换 `--surface-*` / `--text-*` 即可），增量成本小 | 视觉层 |
| 2 | 是否推动 `/chat/stream` 真流式 | **完成 P2 后按体感决定**（§18.2） | 体验上限 |
| 3 | 编辑器是否要富文本 | **不要**。后端落盘是 `.md`，富文本会引入双向转换的坑 | 编辑页 |
| 4 | 是否要移动端独立布局 | 现有 980px 断点方案是"导航折叠 + 单列"；建议先做响应式一致（P0/P1），移动端深度优化放 P6 之后 | 布局 |
| 5 | 图谱是否引入 `d3-force` | **自研**。节点量级（通常 <100）不需要 d3 的完整能力，自研便于控制停帧与降级 | 性能 |

---

## 附录 A：后端 trace 阶段全量清单（已 grep 核实）

| stage | 产生位置 | 语义 |
|---|---|---|
| `classify_intent` | `planner.py:63,71,79` | 意图二分类（COUNSELING / TOOL） |
| `session_init` | `executor.py:39` | 新会话 + 相似记忆检索 |
| `tool_call` | `registry.py:131` | 调用 `psychological_consult_tool` |
| `tool_result` | `registry.py:29,48,81,146,156` | 检索完成 / 预算耗尽 / 异常 |
| `evaluate` | `executor.py:118,129` | 步骤结果评估（失败 / 证据不足） |
| `session_save` | `executor.py:77` | 会话落库 |
| `guided_reasoning` | `guided_plan.py:38,46,61,77,110,119` | 引导链各环节 |
| `preprocess` | `api/tool.py:257` | 文档预处理完成 |
| `chat` | `agent.py:75` | 对话异常兜底 |
| `chat_stream` | `api/chat.py:35` | SSE 异常兜底 |

## 附录 B：设计令牌速查

| 用途 | 令牌 |
|---|---|
| 页面底色 | `--surface` |
| 卡片 / 面板 | `--surface-raised` + `--border-soft` + `--ef-1` |
| 抽屉 / 模态 | `--surface-raised` + `--ef-2` / `--ef-3` |
| 正文 | `--text-primary` + `--fs-base` + `--lh-body` |
| 次级正文 | `--text-secondary` + `--fs-sm` |
| 小字提示 | `--text-tertiary` + `--fs-2xs` |
| 主按钮 | `--accent` 底 + `--text-on-accent` |
| 小号红字 | `--accent-deep`（**不可用 `--accent`**） |
| 焦点环 | `--focus-ring` |
| 章节间距 | `--sp-5` / `--sp-6` |
| 组件内间距 | `--sp-2` / `--sp-3` |
