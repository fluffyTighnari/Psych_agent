/**
 * Markdown-lite 解析器。
 *
 * 为什么自己写而不用 markdown-it：
 * 1) 需要与 [[cite:]] / [[guide:]] 标记共存 —— 引用要渲染成交互 chip 而非文本；
 * 2) 流式场景要能处理「半个标记」：`**` 刚到达一个 `*` 时不能闪烁；
 * 3) 输出为节点树而非 HTML 字符串，组件直接渲染 VNode，**从根上杜绝 XSS**
 *    （全程不碰 innerHTML / v-html）。
 *
 * 支持：**加粗**、*斜体*、`行内代码`、「」衬线强调、标题、有序/无序列表、引用块。
 */

/* ---------- 行内节点 ---------- */

export type InlineNode =
  | { type: 'text'; value: string }
  | { type: 'strong'; children: InlineNode[] }
  | { type: 'em'; children: InlineNode[] }
  | { type: 'code'; value: string }
  /** 「」包裹：用衬线字体，呼应纸感排版 */
  | { type: 'quote'; children: InlineNode[] }
  | { type: 'cite'; id: string }
  | { type: 'guide'; id: string }

export interface InlineResult {
  nodes: InlineNode[]
  /** 尾部可能未闭合的标记，流式时暂存不渲染 */
  blockedTail: string
}

const CITE_RE = /\[\[(cite|guide):([^\]\n]+)\]\]/y
const CITE_OPEN_RE = /\[\[(?:cite|guide)?:?[^\]\n]*$/
/** 流式时尾部若是这些「半截标记」的字符，暂存等下一帧 */
const PARTIAL_TAIL_RE = /[*_`]+$/

const MAX_DEPTH = 5

/**
 * 解析行内标记。
 * @param isFinal 已结束（不再有后续 chunk）时，未闭合标记按普通文本/丢弃处理
 */
export function parseInline(text: string, isFinal = true, depth = 0): InlineResult {
  if (depth > MAX_DEPTH) return { nodes: [{ type: 'text', value: text }], blockedTail: '' }

  const nodes: InlineNode[] = []
  let buf = ''
  let i = 0
  let blockedTail = ''

  const flush = () => {
    if (buf) {
      nodes.push({ type: 'text', value: buf })
      buf = ''
    }
  }

  while (i < text.length) {
    // ---- 引用标记 ----
    if (text.startsWith('[[', i)) {
      CITE_RE.lastIndex = i
      const m = CITE_RE.exec(text)
      if (m) {
        flush()
        nodes.push({ type: m[1] === 'guide' ? 'guide' : 'cite', id: m[2] ?? '' })
        i += m[0].length
        continue
      }
      // 可能是未闭合的引用标记
      const tail = text.slice(i)
      if (CITE_OPEN_RE.test(tail)) {
        if (!isFinal) {
          blockedTail = tail
          i = text.length
          break
        }
        // 已结束仍未闭合 = 模型输出被截断，丢弃残片
        i = text.length
        break
      }
      buf += text[i]
      i++
      continue
    }

    // ---- 行内代码 `code` ----
    if (text[i] === '`') {
      const end = text.indexOf('`', i + 1)
      if (end > i) {
        flush()
        nodes.push({ type: 'code', value: text.slice(i + 1, end) })
        i = end + 1
        continue
      }
      buf += text[i]
      i++
      continue
    }

    // ---- 加粗 **text** ----
    if (text.startsWith('**', i)) {
      const end = text.indexOf('**', i + 2)
      if (end > i + 1) {
        const inner = text.slice(i + 2, end)
        const sub = parseInline(inner, isFinal, depth + 1)
        flush()
        nodes.push({ type: 'strong', children: sub.nodes })
        i = end + 2
        continue
      }
      // 未闭合：流式时暂存，结束时按普通文本保留（避免吞掉内容）
      if (!isFinal) {
        blockedTail = text.slice(i)
        i = text.length
        break
      }
      buf += text.slice(i, i + 2)
      i += 2
      continue
    }

    // ---- 斜体 *text* 或 _text_ ----
    const ch = text[i]
    if (ch === '*' || ch === '_') {
      const end = text.indexOf(ch, i + 1)
      /*
       * 只要求定界符之间有内容（end > i+1）。
       * 不要额外要求最小长度 —— `*斜*` 是合法的单字斜体，
       * 过度保守的守卫会让嵌套在加粗里的短斜体解析失败。
       */
      if (end > i + 1) {
        const inner = text.slice(i + 1, end)
        const sub = parseInline(inner, isFinal, depth + 1)
        flush()
        nodes.push({ type: 'em', children: sub.nodes })
        i = end + 1
        continue
      }
      if (!isFinal && end < 0) {
        // 可能是跨 chunk 的斜体标记
        blockedTail = text.slice(i)
        i = text.length
        break
      }
      buf += ch
      i++
      continue
    }

    // ---- 「」强调：换衬线字体 ----
    if (ch === '「') {
      const end = text.indexOf('」', i + 1)
      if (end > i + 1) {
        const inner = text.slice(i + 1, end)
        const sub = parseInline(inner, isFinal, depth + 1)
        flush()
        nodes.push({ type: 'quote', children: sub.nodes })
        i = end + 1
        continue
      }
      // 没找到闭合：按普通字符处理（「」在中文里也可能单独出现）
      buf += ch
      i++
      continue
    }

    buf += ch
    i++
  }

  flush()

  // 流式收尾：尾部若是半截强调符，暂存避免闪烁
  if (!isFinal && !blockedTail) {
    const last = nodes[nodes.length - 1]
    if (last && last.type === 'text') {
      const m = last.value.match(PARTIAL_TAIL_RE)
      if (m) {
        blockedTail = m[0]
        last.value = last.value.slice(0, last.value.length - blockedTail.length)
        if (!last.value) nodes.pop()
      }
    }
  }

  return { nodes, blockedTail }
}

/* ---------- 块级节点 ---------- */

export type BlockNode =
  | { type: 'paragraph'; children: InlineNode[] }
  | { type: 'heading'; level: number; children: InlineNode[] }
  | { type: 'list'; ordered: boolean; items: InlineNode[][] }
  | { type: 'blockquote'; children: InlineNode[] }
  | { type: 'codeblock'; value: string; lang: string }

const HEADING_RE = /^(#{1,4})\s+(.*)$/
const UL_RE = /^\s*[-*+]\s+(.*)$/
const OL_RE = /^\s*\d+[.)]\s+(.*)$/
const BQ_RE = /^\s*>\s?(.*)$/
const FENCE_RE = /^\s*```(\w*)\s*$/

/** 解析整段文本为块级结构 */
export function parseBlocks(text: string, isFinal = true): BlockNode[] {
  const lines = text.split(/\r?\n/)
  const blocks: BlockNode[] = []

  let para: string[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let bq: string[] = []
  let fence: { lang: string; lines: string[] } | null = null

  const inline = (s: string) => parseInline(s, isFinal).nodes

  const flushPara = () => {
    if (para.length) {
      blocks.push({ type: 'paragraph', children: inline(para.join('\n')) })
      para = []
    }
  }
  const flushList = () => {
    if (list) {
      blocks.push({
        type: 'list',
        ordered: list.ordered,
        items: list.items.map((it) => inline(it)),
      })
      list = null
    }
  }
  const flushBq = () => {
    if (bq.length) {
      blocks.push({ type: 'blockquote', children: inline(bq.join('\n')) })
      bq = []
    }
  }
  const flushAll = () => {
    flushPara()
    flushList()
    flushBq()
  }

  for (const line of lines) {
    // ---- 代码块 ----
    if (fence) {
      const close = FENCE_RE.exec(line)
      if (close) {
        blocks.push({
          type: 'codeblock',
          lang: fence.lang,
          value: fence.lines.join('\n'),
        })
        fence = null
      } else {
        fence.lines.push(line)
      }
      continue
    }
    const openFence = FENCE_RE.exec(line)
    if (openFence) {
      flushAll()
      fence = { lang: openFence[1] ?? '', lines: [] }
      continue
    }

    if (!line.trim()) {
      flushAll()
      continue
    }

    // ---- 引用块 ----
    const bqMatch = BQ_RE.exec(line)
    if (bqMatch) {
      flushPara()
      flushList()
      bq.push(bqMatch[1] ?? '')
      continue
    }

    // ---- 标题 ----
    const h = HEADING_RE.exec(line)
    if (h) {
      flushAll()
      blocks.push({ type: 'heading', level: (h[1] ?? '#').length, children: inline(h[2] ?? '') })
      continue
    }

    // ---- 列表 ----
    const ol = OL_RE.exec(line)
    const ul = UL_RE.exec(line)
    if (ol || ul) {
      flushPara()
      flushBq()
      const ordered = !!ol
      const content = (ol?.[1] ?? ul?.[1] ?? '').trim()
      if (list && list.ordered !== ordered) flushList()
      if (!list) list = { ordered, items: [] }
      list.items.push(content)
      continue
    }

    // ---- 普通段落（续行）----
    flushList()
    flushBq()
    para.push(line)
  }

  // 未闭合的代码块：把已收集内容按代码块输出（流式中很常见）
  if (fence) {
    blocks.push({ type: 'codeblock', lang: fence.lang, value: fence.lines.join('\n') })
  }

  flushAll()
  return blocks
}

/** 去标记取纯文本（复制、摘要用） */
export function toPlainText(text: string): string {
  return text
    .replace(/\[\[(?:cite|guide):[^\]\n]+\]\]/g, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/[「」]/g, '')
    .replace(/^#{1,4}\s+/gm, '')
    .trim()
}
