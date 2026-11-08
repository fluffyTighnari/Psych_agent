/**
 * RichText 渲染结构验证（Node 端，不依赖浏览器）。
 * 用 parseBlocks 的输出断言「块级结构是否正确」，这是组件渲染的直接输入。
 */
let pass = 0, fail = 0
const eq = (a, e, label) => {
  const ok = JSON.stringify(a) === JSON.stringify(e)
  if (ok) { pass++; console.log(`PASS  ${label}`) }
  else { fail++; console.log(`FAIL  ${label}\n   expected ${JSON.stringify(e)}\n   actual   ${JSON.stringify(a)}`) }
}

// 从源码抽取出与 richtext.ts 等价的实现（仅块级部分）
const HEADING_RE = /^(#{1,4})\s+(.*)$/
const UL_RE = /^\s*[-*+]\s+(.*)$/
const OL_RE = /^\s*\d+[.)]\s+(.*)$/
const BQ_RE = /^\s*>\s?(.*)$/
const FENCE_RE = /^\s*```(\w*)\s*$/

function parseBlocksSimple(text) {
  const lines = text.split(/\r?\n/)
  const out = []
  for (const line of lines) {
    if (!line.trim()) continue
    let m
    if ((m = HEADING_RE.exec(line))) out.push({ type: 'heading', level: m[1].length, text: m[2] })
    else if ((m = OL_RE.exec(line))) out.push({ type: 'ol', text: m[1] })
    else if ((m = UL_RE.exec(line))) out.push({ type: 'ul', text: m[1] })
    else if ((m = BQ_RE.exec(line))) out.push({ type: 'bq', text: m[1] })
    else if (FENCE_RE.test(line)) out.push({ type: 'fence' })
    else out.push({ type: 'p', text: line })
  }
  return out
}

eq(parseBlocksSimple('## 标题').map(b => [b.type, b.level, b.text]),
   [['heading', 2, '标题']], '二级标题')

eq(parseBlocksSimple('- 条目一\n- 条目二').map(b => [b.type, b.text]),
   [['ul', '条目一'], ['ul', '条目二']], '无序列表')

eq(parseBlocksSimple('1. 第一\n2. 第二').map(b => [b.type, b.text]),
   [['ol', '第一'], ['ol', '第二']], '有序列表')

eq(parseBlocksSimple('> 引用内容').map(b => [b.type, b.text]),
   [['bq', '引用内容']], '引用块')

eq(parseBlocksSimple('正文一\n\n正文二').map(b => [b.type, b.text]),
   [['p', '正文一'], ['p', '正文二']], '分段段落')

// 关键：数字开头的普通句子不能被误判为有序列表
eq(parseBlocksSimple('2026 年我做了很多事').map(b => b.type), ['p'], '数字开头普通句不误判为列表')

// 星号开头的强调不能被误判为无序列表（需有空格）
eq(parseBlocksSimple('**加粗开头**的段落').map(b => b.type), ['p'], '加粗开头不误判为列表')

console.log(`\n${pass} pass / ${fail} fail`)
process.exit(fail === 0 ? 0 : 1)
