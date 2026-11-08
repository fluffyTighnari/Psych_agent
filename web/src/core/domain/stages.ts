import type { TraceItem } from '@/core/api/types'
import type { IconName } from '@/components/ui/icon-names'

/**
 * trace stage → 语义阶段的映射。
 *
 * 后端产生的阶段名在附录 A 已全量核实。这里的关键设计：
 * **未知阶段不隐藏、不报错**，落到 other 并保留原始 stage 名。
 * 否则后端新增一个阶段，前端会静默丢失信息。
 */

export type StageKey =
  | 'classify'
  | 'session_init'
  | 'retrieve'
  | 'generate'
  | 'evaluate'
  | 'save'
  | 'guided'
  | 'other'

export interface StageDef {
  key: StageKey
  title: string
  icon: IconName
}

const DEFS: Record<string, StageDef> = {
  // ---- 对话链路 ----
  classify_intent: { key: 'classify', title: '理解意图', icon: 'compass' },
  session_init: { key: 'session_init', title: '唤起记忆', icon: 'memory' },
  tool_call: { key: 'retrieve', title: '处理中', icon: 'tool' },
  tool_result: { key: 'retrieve', title: '检索与生成', icon: 'search' },
  // CRAG 补救：证据不足时自动分解查询 / 扩名额重检（core/orchestrator/remediation.py）
  remediation: { key: 'retrieve', title: '补充检索', icon: 'refresh' },
  evaluate: { key: 'evaluate', title: '校验证据', icon: 'check' },
  session_save: { key: 'save', title: '保存会话', icon: 'save' },
  guided_reasoning: { key: 'guided', title: '引导推理', icon: 'route' },
  fallback: { key: 'other', title: '降级兜底', icon: 'alert' },

  // ---- 检索链路（检索调试页也用）----
  optimize_prompt: { key: 'retrieve', title: '改写查询', icon: 'compass' },
  decompose_query: { key: 'retrieve', title: '分解查询', icon: 'list' },
  retrieve_dense: { key: 'retrieve', title: '向量召回', icon: 'search' },
  retrieve_sparse: { key: 'retrieve', title: '关键词召回', icon: 'search' },
  rerank: { key: 'retrieve', title: '重排', icon: 'filter' },
  retrieve_final: { key: 'retrieve', title: '最终结果', icon: 'check' },

  // ---- 微服务 / 缓存准备 ----
  document_load: { key: 'other', title: '加载文档', icon: 'doc' },
  vector_db: { key: 'other', title: '向量库', icon: 'archive' },
  memory_vector_db: { key: 'other', title: '记忆向量库', icon: 'archive' },
  meta_db: { key: 'other', title: '元数据库', icon: 'archive' },
  knowledge_cache: { key: 'other', title: '知识缓存', icon: 'archive' },
  memory_cache: { key: 'other', title: '记忆缓存', icon: 'archive' },
  knowledge_load: { key: 'other', title: '加载知识', icon: 'doc' },
  memory_load: { key: 'other', title: '加载记忆', icon: 'memory' },

  // ---- 其余 ----
  preprocess: { key: 'other', title: '预处理', icon: 'settings' },
  summarize_memory: { key: 'save', title: '总结记忆', icon: 'save' },
  chat: { key: 'other', title: '对话', icon: 'chat' },
  chat_stream: { key: 'other', title: '对话', icon: 'chat' },
}

export function resolveStage(stage: string): StageDef {
  return DEFS[stage] ?? { key: 'other', title: stage || '未知阶段', icon: 'info' }
}

/** 结构化摘要：把 content 里的原始字段压成一句人话 */
export interface StageDetail {
  /** 主摘要，如「2 原则 · 1 经历」 */
  summary: string
  /** 次要徽章，如 COUNSELING */
  badge?: string
  /** 需要展开查看的明细键值 */
  rows: { k: string; v: string }[]
  /** 引发警示的原因（证据不足 / 预算耗尽等） */
  warn?: string
  /** 可点击跳转的文档 ID */
  docIds: string[]
}

function str(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function num(v: unknown): number | null {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function arr(v: unknown): string[] {
  return Array.isArray(v) ? v.map(str).filter(Boolean) : []
}

/**
 * 从 trace content 提取可读摘要。
 * 每个 stage 关心的字段不同，这里集中处理，避免 UI 里写一堆 if。
 */
export function extractDetail(item: TraceItem): StageDetail | null {
  const c = item.content ?? {}
  const rows: { k: string; v: string }[] = []
  const def = resolveStage(item.stage)

  switch (item.stage) {
    case 'classify_intent': {
      const result = str(c.result)
      if (!result) return null
      return {
        summary: result === 'COUNSELING' ? '心理咨询倾诉' : result === 'TOOL' ? '工具请求' : result,
        badge: result,
        rows: [],
        docIds: [],
      }
    }

    case 'session_init': {
      const memCount = num(c.memory_count) ?? 0
      const memIds = arr(c.memory_ids)
      if (memIds.length) rows.push({ k: '记忆', v: memIds.join(', ') })
      const sid = str(c.session_id)
      if (sid) rows.push({ k: '会话', v: sid })
      return {
        summary: `匹配 ${memCount} 条相似记忆`,
        rows,
        docIds: [],
      }
    }

    case 'tool_result': {
      const query = str(c.query)
      if (query) rows.push({ k: '检索词', v: query })

      const principle = num(c.principle_count)
      const experience = num(c.experience_count)

      // evidence 相关（阶段 4-C）
      const evidenceStatus = str(c.evidence_status)
      const topScore = c.top_score
      const remediation = str(c.remediation_action)

      if (principle !== null || experience !== null) {
        const p = principle ?? 0
        const e = experience ?? 0
        const docIds = arr(c.doc_ids)
        if (docIds.length) rows.push({ k: '文档 ID', v: docIds.join(', ') })
        if (evidenceStatus) rows.push({ k: '证据', v: evidenceStatus })
        if (topScore !== undefined && topScore !== null) rows.push({ k: '最高分', v: str(topScore) })
        if (remediation) rows.push({ k: '补救', v: remediation })

        let warn: string | undefined
        if (remediation) {
          warn =
            remediation === 'decompose'
              ? '首次证据不足，已自动分解查询重检'
              : remediation === 'expand'
                ? '首次证据不足，已自动扩大召回名额重检'
                : '证据不足，已执行补救'
        }

        return {
          summary: `${p} 原则 · ${e} 经历`,
          rows,
          warn,
          docIds,
        }
      }

      // 非检索类工具结果（如 psychological_consult_tool 完成）
      const refDocs = arr(c.referenced_docs)
      if (refDocs.length) {
        rows.push({ k: '引用文档', v: refDocs.join(', ') })
        const rp = num(c.principle_count)
        const re = num(c.experience_count)
        return {
          summary: `${rp ?? 0} 原则 · ${re ?? 0} 经历`,
          rows,
          docIds: refDocs,
        }
      }

      // 预算耗尽 / 异常
      const budget = c.budget_left
      if (budget !== undefined) {
        return {
          summary: '检索预算已用尽',
          rows,
          warn: '单轮最多检索 2 次，后续直接生成',
          docIds: [],
        }
      }
      return rows.length ? { summary: '', rows, docIds: [] } : null
    }

    case 'evaluate': {
      // evidence_status 的原始值（strong/weak/gap/evidence_gap）需要可读化
      const raw = str(c.status) || str(c.evidence_status) || str(c.reason)
      const statusLabel: Record<string, string> = {
        strong: '证据充分',
        ok: '证据可用',
        weak: '证据偏弱',
        gap: '证据不足',
        evidence_gap: '证据不足',
      }
      const topScore = c.top_score
      if (topScore !== undefined && topScore !== null) rows.push({ k: '最高分', v: str(topScore) })
      if (raw) rows.push({ k: '原始判定', v: raw })
      const remediation = str(c.remediation_action)
      if (remediation) rows.push({ k: '补救', v: remediation })

      const label = statusLabel[raw] ?? (raw || (item.is_error ? '评估失败' : '已评估'))
      return {
        summary: label,
        rows,
        warn: raw === 'gap' || raw === 'evidence_gap' ? '检索证据不足，可补充更具体的描述' : undefined,
        docIds: [],
      }
    }

    case 'remediation': {
      // CRAG 补救：content 里可能有 action（decompose/expand）与 queries
      const action = str(c.action) || str(c.remediation_action)
      const queries = arr(c.queries)
      const docCount = num(c.doc_count) ?? num(c.remediation_doc_count)

      if (action) rows.push({ k: '补救方式', v: action })
      if (queries.length) rows.push({ k: '子查询', v: queries.join(' / ') })
      if (docCount !== null) rows.push({ k: '新增文档', v: String(docCount) })
      for (const [k, v] of Object.entries(c)) {
        if (v !== null && typeof v !== 'object' && !rows.some((r) => r.k === k)) {
          rows.push({ k, v: str(v) })
        }
      }

      const summary =
        action === 'decompose'
          ? `分解为 ${queries.length || '多'} 条子查询重检`
          : action === 'expand'
            ? '扩大召回名额重检'
            : '已执行补充检索'

      return { summary, rows, warn: '首次证据不足，已自动补充检索', docIds: [] }
    }

    case 'session_save': {
      const turns = num(c.dialogue_turns) ?? 0
      const docs = num(c.referenced_docs) ?? 0
      const mems = num(c.similar_memories) ?? 0
      if (mems) rows.push({ k: '相似记忆', v: String(mems) })
      return {
        summary: `${turns} 轮对话 · 提及 ${docs} 篇文档`,
        rows,
        docIds: [],
      }
    }

    case 'guided_reasoning': {
      const isNew = c.new_chain
      const docIds = arr(c.doc_ids)
      if (docIds.length) rows.push({ k: '文档 ID', v: docIds.join(', ') })
      const memCount = num(c.memory_count)
      if (memCount !== null) rows.push({ k: '记忆', v: String(memCount) })

      if (isNew === true) {
        return { summary: '开启新的引导链，已检索知识', rows, docIds }
      }
      if (isNew === false) {
        return { summary: '承接上一问，跳过检索', rows, docIds }
      }
      return rows.length ? { summary: '', rows, docIds } : null
    }

    default: {
      // 未知阶段：把 content 的扁平字段全列出来，至少不丢信息
      for (const [k, v] of Object.entries(c)) {
        if (v !== null && typeof v !== 'object') rows.push({ k, v: str(v) })
      }
      return rows.length ? { summary: def.title, rows, docIds: [] } : null
    }
  }
}

/* ---------- 阶段时长 ---------- */

export interface TimedStage {
  item: TraceItem
  /** 毫秒；null 表示还没有下一个阶段可比 */
  durationMs: number | null
}

/**
 * 计算每个阶段的耗时。
 * 用相邻 trace 的 timestamp 差值 —— 这是后端真实产生的时刻，不是伪造进度。
 */
export function computeDurations(items: TraceItem[], finishedAt?: number | null): TimedStage[] {
  return items.map((item, i) => {
    const next = items[i + 1]
    const endTs = next ? next.timestamp : finishedAt ? finishedAt / 1000 : null
    const durationMs = endTs === null ? null : Math.max(0, (endTs - item.timestamp) * 1000)
    return { item, durationMs }
  })
}

/** 阶段名对人友好化：tool_call 的 label 里含工具名，取出来做标题更准确 */
export function stageLabel(item: TraceItem): string {
  const def = resolveStage(item.stage)

  if (item.stage === 'tool_call') {
    const m = item.label.match(/工具[:：]\s*(\w+)/)
    if (m?.[1]) {
      const tool = m[1]
      if (tool === 'retrieve_knowledge_tool') return '检索知识'
      if (tool === 'psychological_consult_tool') return '生成回复'
      return tool
    }
  }
  if (item.stage === 'tool_result') {
    if (item.label.includes('retrieve_knowledge_tool')) return '检索结果'
    if (item.label.includes('psychological_consult_tool')) return '生成完成'
    if (item.label.includes('预算')) return '检索预算'
  }
  return def.title
}
