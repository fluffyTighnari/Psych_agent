/** Markdown-lite 解析单测 */
let pass = 0, fail = 0
const eq = (a, e, label) => {
  const ok = JSON.stringify(a) === JSON.stringify(e)
  if (ok) { pass++; console.log(`PASS  ${label}`) }
  else { fail++; console.log(`FAIL  ${label}\n   expected ${JSON.stringify(e)}\n   actual   ${JSON.stringify(a)}`) }
}

/* 复刻 richtext.ts 的行内解析核心（与源码保持一致） */
const CITE_RE = /\[\[(cite|guide):([^\]\n]+)\]\]/y
const CITE_OPEN_RE = /\[\[(?:cite|guide)?:?[^\]\n]*$/
const PARTIAL_TAIL_RE = /[*_`]+$/

function parseInline(text, isFinal = true, depth = 0) {
  if (depth > 5) return { nodes: [{ type: 'text', value: text }], blockedTail: '' }
  const nodes = []
  let buf = '', i = 0, blockedTail = ''
  const flush = () => { if (buf) { nodes.push({ type: 'text', value: buf }); buf = '' } }

  while (i < text.length) {
    if (text.startsWith('[[', i)) {
      CITE_RE.lastIndex = i
      const m = CITE_RE.exec(text)
      if (m) { flush(); nodes.push({ type: m[1] === 'guide' ? 'guide' : 'cite', id: m[2] ?? '' }); i += m[0].length; continue }
      const tail = text.slice(i)
      if (CITE_OPEN_RE.test(tail)) {
        if (!isFinal) { blockedTail = tail; i = text.length; break }
        i = text.length; break
      }
      buf += text[i]; i++; continue
    }
    if (text[i] === '`') {
      const end = text.indexOf('`', i + 1)
      if (end > i) { flush(); nodes.push({ type: 'code', value: text.slice(i + 1, end) }); i = end + 1; continue }
      buf += text[i]; i++; continue
    }
    if (text.startsWith('**', i)) {
      const end = text.indexOf('**', i + 2)
      if (end > i + 1) {
        const sub = parseInline(text.slice(i + 2, end), isFinal, depth + 1)
        flush(); nodes.push({ type: 'strong', children: sub.nodes }); i = end + 2; continue
      }
      if (!isFinal) { blockedTail = text.slice(i); i = text.length; break }
      buf += text.slice(i, i + 2); i += 2; continue
    }
    const ch = text[i]
    if (ch === '*' || ch === '_') {
      const end = text.indexOf(ch, i + 1)
      if (end > i + 1) {
        const sub = parseInline(text.slice(i + 1, end), isFinal, depth + 1)
        flush(); nodes.push({ type: 'em', children: sub.nodes }); i = end + 1; continue
      }
      if (!isFinal && end < 0) { blockedTail = text.slice(i); i = text.length; break }
      buf += ch; i++; continue
    }
    if (ch === '「') {
      const end = text.indexOf('」', i + 1)
      if (end > i + 1) {
        const sub = parseInline(text.slice(i + 1, end), isFinal, depth + 1)
        flush(); nodes.push({ type: 'quote', children: sub.nodes }); i = end + 1; continue
      }
      buf += ch; i++; continue
    }
    buf += ch; i++
  }
  flush()
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

/* ---- 加粗 ---- */
eq(parseInline('这是**重点**内容').nodes, [
  { type: 'text', value: '这是' },
  { type: 'strong', children: [{ type: 'text', value: '重点' }] },
  { type: 'text', value: '内容' },
], '加粗')

/* ---- 斜体 ---- */
eq(parseInline('*倾斜*文字').nodes, [
  { type: 'em', children: [{ type: 'text', value: '倾斜' }] },
  { type: 'text', value: '文字' },
], '斜体')

/* ---- 行内代码 ---- */
eq(parseInline('用 `code()` 调用').nodes, [
  { type: 'text', value: '用 ' },
  { type: 'code', value: 'code()' },
  { type: 'text', value: ' 调用' },
], '行内代码')

/* ---- 「」衬线强调 ---- */
eq(parseInline('你真正害怕的是「被否定」').nodes, [
  { type: 'text', value: '你真正害怕的是' },
  { type: 'quote', children: [{ type: 'text', value: '被否定' }] },
], '「」强调')

/* ---- 嵌套：加粗里含斜体 ---- */
eq(parseInline('**粗*斜*体**').nodes, [
  { type: 'strong', children: [
    { type: 'text', value: '粗' },
    { type: 'em', children: [{ type: 'text', value: '斜' }] },
    { type: 'text', value: '体' },
  ] },
], '嵌套加粗+斜体')

/* ---- 引用标记与加粗共存 ---- */
eq(parseInline('你说的**很有道理**[[cite:abc]]').nodes, [
  { type: 'text', value: '你说的' },
  { type: 'strong', children: [{ type: 'text', value: '很有道理' }] },
  { type: 'cite', id: 'abc' },
], '加粗与引用共存')

/* ---- 流式：未闭合的加粗暂存 ---- */
const r1 = parseInline('这是**未完', false)
eq(r1.blockedTail, '**未完', '流式中未闭合加粗进入 blockedTail')
eq(r1.nodes, [{ type: 'text', value: '这是' }], '流式中未闭合加粗不渲染')

/* ---- 流式：尾部单个 * 暂存，避免闪烁 ---- */
const r2 = parseInline('文本*', false)
eq(r2.blockedTail, '*', '尾部单个 * 被暂存')
eq(r2.nodes, [{ type: 'text', value: '文本' }], '尾部单 * 不渲染')

/* ---- 流式：未闭合引用标记 ---- */
eq(parseInline('文本[[cite:ab', false).blockedTail, '[[cite:ab', '流式中未闭合引用标记暂存')

/* ---- 已结束后未闭合的引用标记被丢弃 ---- */
eq(parseInline('文本[[cite:ab', true).nodes, [{ type: 'text', value: '文本' }], '结束时截断标记被丢弃')

/* ---- 已结束后未闭合的加粗按字面保留（不吞内容） ---- */
eq(parseInline('这是**未完', true).nodes, [{ type: 'text', value: '这是**未完' }], '结束时未闭合加粗保留字面')

/* ---- 单独的「不构成强调 ---- */
eq(parseInline('他说「然后就没下文了。').nodes, [
  { type: 'text', value: '他说「然后就没下文了。' },
], '未闭合「按普通字符处理')

/* ---- 空文本 ---- */
eq(parseInline('').nodes, [], '空文本')

console.log(`\n${pass} pass / ${fail} fail`)
process.exit(fail === 0 ? 0 : 1)
