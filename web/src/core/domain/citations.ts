import type { Document, GraphNode, Memory } from '@/core/api/types'

/**
 * 引用解析。
 *
 * 关键事实（设计文档 §1.7）：`[[cite:ID]]` 里的 ID **既可能是文档 ID，也可能是记忆 ID**
 * —— RAG prompt 的 format_principle / format_experience / _format_memories_for_prompt
 * 都会输出 `ID:` 字段。所以必须双查，不能假定只有文档。
 */

export type CitationKind = 'document' | 'memory' | 'reason' | 'unknown'

export interface Citation {
  id: string
  kind: CitationKind
  /** 展示用序号，按首次出现顺序分配，同一 ID 复用同号 */
  index: number
  title: string
}

export const CITE_RE = /\[\[cite:([^\]\n]+)\]\]/g
export const GUIDE_RE = /\[\[guide:([^\]\n]+)\]\]/g

/** 匹配任意一种标记（用于 segmentation 时统一处理） */
export const ANY_MARK_RE = /\[\[(cite|guide):([^\]\n]+)\]\]/g

export interface CitationContext {
  docs: Map<string, Document>
  memories: Map<string, Memory>
  nodes: Map<string, GraphNode>
}

export function buildCitationContext(
  docs: Document[],
  memories: Memory[],
  nodes: GraphNode[] = [],
): CitationContext {
  return {
    docs: new Map(docs.map((d) => [d.doc_id, d])),
    memories: new Map(memories.map((m) => [m.id, m])),
    nodes: new Map(nodes.map((n) => [n.id, n])),
  }
}

function lookup(id: string, ctx: CitationContext): { kind: CitationKind; title: string } {
  const doc = ctx.docs.get(id)
  if (doc) return { kind: 'document', title: doc.title || id }

  const mem = ctx.memories.get(id)
  if (mem) return { kind: 'memory', title: mem.title || id }

  const node = ctx.nodes.get(id)
  if (node) {
    return {
      kind: node.type === 'reason' ? 'reason' : node.type === 'memory' ? 'memory' : 'document',
      title: node.name || id,
    }
  }

  // 推理节点命名约定为 reason_N（后端 guided_plan 生成）
  if (/^reason_\d+$/.test(id)) return { kind: 'reason', title: `引导问题 ${Number(id.slice(7)) + 1}` }

  return { kind: 'unknown', title: id }
}

/**
 * 从一段回复里提取所有引用，按首次出现顺序编号。
 * 返回的 Map 供渲染时按 id 查序号。
 */
export function extractCitations(text: string, ctx: CitationContext): Map<string, Citation> {
  const result = new Map<string, Citation>()
  let index = 0

  const re = new RegExp(ANY_MARK_RE.source, 'g')
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const kindMark = m[1]
    const id = m[2]
    if (!id || result.has(id)) continue

    const { kind: resolvedKind, title } = lookup(id, ctx)
    const kind = kindMark === 'guide' ? 'reason' : resolvedKind
    result.set(id, { id, kind, index: ++index, title })
  }

  return result
}

/* ---------- 回复分段 ---------- */

export type ReplySegment =
  | { kind: 'text'; content: string }
  | { kind: 'advice'; content: string }

/**
 * 引导结束时会拼 `【建议总结】\n{report}` 到同一条消息里（guided_plan.py:140）。
 * 这两段语义不同，必须拆开渲染：前段是引导收束，后段是完整的建议报告。
 */
const ADVICE_MARK = '【建议总结】'

/**
 * 工具哨兵前缀。
 *
 * 后端 `parse_tool_result` 会剥离它们，但历史落库数据与旧会话里仍可能带
 * `【心理咨询回复】` 这类协议标记。前端渲染前再过一遍，保证正文干净。
 */
const SENTINEL_PREFIXES = [
  '【心理咨询回复】',
  '【引导提问】',
  '【模糊筛选匹配结果】',
  '【精准文本匹配结果】',
  '【记忆搜索结果】',
  '【精准记忆筛选结果】',
  '【会话总结完成】',
]

export function stripSentinels(text: string): string {
  let out = text ?? ''
  for (const p of SENTINEL_PREFIXES) {
    if (out.startsWith(p)) out = out.slice(p.length)
    out = out.split(p).join('')
  }
  // 去掉剥离后残留的前导空行
  return out.replace(/^[\s\r\n]+/, '')
}

export function splitReply(input: string): ReplySegment[] {
  // 先剥离哨兵，再做分段（历史数据可能带【心理咨询回复】前缀）
  const raw = stripSentinels(input)
  const idx = raw.indexOf(ADVICE_MARK)
  if (idx < 0) return raw.trim() ? [{ kind: 'text', content: raw }] : []

  const head = raw.slice(0, idx).trim()
  const advice = raw.slice(idx + ADVICE_MARK.length).trim()

  const segments: ReplySegment[] = []
  if (head) segments.push({ kind: 'text', content: head })
  if (advice) segments.push({ kind: 'advice', content: advice })
  return segments
}

/* ---------- 流式增量渲染的分块 ---------- */

export type InlineToken =
  | { type: 'text'; value: string }
  | { type: 'cite'; id: string }
  | { type: 'guide'; id: string }

/**
 * 把文本切成「纯文本 / 引用标记」的片段序列。
 *
 * 流式场景要处理跨 chunk 的半个标记：调用方应传入 isFinal，
 * 非最终状态下若尾部是未闭合的 `[[...`，要把该片段返回 blockedTail 暂存。
 */
export interface TokenizeResult {
  tokens: InlineToken[]
  /** 尾部未闭合的标记前缀，需等后续 chunk 拼接，不应渲染 */
  blockedTail: string
}

const OPEN_TAIL_RE = /\[\[(?:cite|guide)?:?[^\]\n]*$/

export function tokenizeInline(text: string, isFinal = true): TokenizeResult {
  const tokens: InlineToken[] = []
  const re = new RegExp(ANY_MARK_RE.source, 'g')
  let cursor = 0
  let m: RegExpExecArray | null

  while ((m = re.exec(text)) !== null) {
    const start = m.index
    if (start > cursor) tokens.push({ type: 'text', value: text.slice(cursor, start) })
    tokens.push({ type: m[1] === 'guide' ? 'guide' : 'cite', id: m[2] ?? '' })
    cursor = start + m[0].length
  }

  let rest = text.slice(cursor)
  let blockedTail = ''

  // 尾部可能是被切开的标记：`[[`、`[[cite:abc` 等
  const tailMatch = rest.match(OPEN_TAIL_RE)
  if (tailMatch) {
    if (!isFinal) {
      // 流式中：暂存，等后续 chunk 补齐
      blockedTail = tailMatch[0]
      rest = rest.slice(0, rest.length - blockedTail.length)
    } else {
      // 已结束仍未闭合 = 模型输出被截断，标记残缺。
      // 直接丢弃这段残片，不要把 `[[cite:ab` 这种字面量展示给用户。
      rest = rest.slice(0, rest.length - tailMatch[0].length)
    }
  }

  if (rest) tokens.push({ type: 'text', value: rest })

  return { tokens, blockedTail }
}

/** 去掉所有标记，得到纯文本（用于复制、ThreadRail 摘要、字数统计） */
export function stripMarks(text: string): string {
  return text.replace(ANY_MARK_RE, '').replace(/\[\[(cite|guide):[^\]\n]*$/g, '').trim()
}

/** 类型 → 展示标签 */
export const KIND_LABEL: Record<CitationKind, string> = {
  document: '文档',
  memory: '记忆',
  reason: '推理',
  unknown: '引用',
}

/** 类型 → 图标 */
export const KIND_ICON = {
  document: 'doc',
  memory: 'memory',
  reason: 'route',
  unknown: 'quote',
} as const
