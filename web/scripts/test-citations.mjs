/** 引用解析与回复分段单测 */
let pass = 0, fail = 0
const eq = (a, e, label) => {
  const ok = JSON.stringify(a) === JSON.stringify(e)
  if (ok) { pass++; console.log(`PASS  ${label}`) }
  else { fail++; console.log(`FAIL  ${label}\n   expected ${JSON.stringify(e)}\n   actual   ${JSON.stringify(a)}`) }
}

const ANY = /\[\[(cite|guide):([^\]\n]+)\]\]/g

function splitReply(raw) {
  const MARK = '【建议总结】'
  const idx = raw.indexOf(MARK)
  if (idx < 0) return raw.trim() ? [{ kind: 'text', content: raw }] : []
  const head = raw.slice(0, idx).trim()
  const advice = raw.slice(idx + MARK.length).trim()
  const out = []
  if (head) out.push({ kind: 'text', content: head })
  if (advice) out.push({ kind: 'advice', content: advice })
  return out
}

const OPEN_TAIL = /\[\[(?:cite|guide)?:?[^\]\n]*$/
function tokenizeInline(text, isFinal = true) {
  const tokens = []
  const re = new RegExp(ANY.source, 'g')
  let cursor = 0, m
  while ((m = re.exec(text)) !== null) {
    if (m.index > cursor) tokens.push({ type: 'text', value: text.slice(cursor, m.index) })
    tokens.push({ type: m[1] === 'guide' ? 'guide' : 'cite', id: m[2] })
    cursor = m.index + m[0].length
  }
  let rest = text.slice(cursor), blockedTail = ''
  const t = rest.match(OPEN_TAIL)
  if (t) {
    if (!isFinal) {
      blockedTail = t[0]
      rest = rest.slice(0, rest.length - blockedTail.length)
    } else {
      rest = rest.slice(0, rest.length - t[0].length)
    }
  }
  if (rest) tokens.push({ type: 'text', value: rest })
  return { tokens, blockedTail }
}

/* ---- 建议报告分段 ---- */
eq(splitReply('你现在害怕的其实是别人的评价。'), [{ kind: 'text', content: '你现在害怕的其实是别人的评价。' }], '无建议标记：整段文本')
eq(
  splitReply('引导收束。\n\n【建议总结】\n完整的建议报告内容。'),
  [{ kind: 'text', content: '引导收束。' }, { kind: 'advice', content: '完整的建议报告内容。' }],
  '有建议标记：拆成两段',
)
eq(splitReply('【建议总结】\n只有报告'), [{ kind: 'advice', content: '只有报告' }], '仅报告无前文')
eq(splitReply(''), [], '空文本返回空数组')

/* ---- 引用 token 化 ---- */
eq(
  tokenizeInline('你之前写过类似的话[[cite:abc123]]，现在呢？'),
  {
    tokens: [
      { type: 'text', value: '你之前写过类似的话' },
      { type: 'cite', id: 'abc123' },
      { type: 'text', value: '，现在呢？' },
    ],
    blockedTail: '',
  },
  '完整引用标记被切出',
)

eq(
  tokenizeInline('引导问题[[guide:reason_0]]'),
  { tokens: [{ type: 'text', value: '引导问题' }, { type: 'guide', id: 'reason_0' }], blockedTail: '' },
  'guide 标记识别为推理节点',
)

// 跨 chunk：半个标记不渲染
eq(
  tokenizeInline('文本[[cite:ab', false).blockedTail,
  '[[cite:ab',
  '流式中未闭合标记进入 blockedTail',
)
eq(
  tokenizeInline('文本[[cite:ab', false).tokens,
  [{ type: 'text', value: '文本' }],
  '未闭合标记不产生 cite token',
)
eq(
  tokenizeInline('文本[[cite:ab', true).tokens,
  [{ type: 'text', value: '文本' }],
  '结束时未闭合标记也不渲染',
)

// 回归：多个引用连续出现
eq(
  tokenizeInline('A[[cite:x]]B[[cite:y]]C').tokens.map((t) => t.type),
  ['text', 'cite', 'text', 'cite', 'text'],
  '多个引用连续出现',
)

/* 占位符 ID 的回归测试在 test-citations-src.mjs —— 那里直接加载真实源码，
   不手抄实现，能真正捕捉源码回归。本文件只保留纯函数级的手工用例。 */

console.log(`\n${pass} pass / ${fail} fail`)
process.exit(fail === 0 ? 0 : 1)
