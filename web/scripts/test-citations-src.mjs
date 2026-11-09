/**
 * 占位符 ID 回归测试。
 *
 * 与 test-citations.mjs 不同，这里**直接加载真实源码**（用 esbuild 转译 TS），
 * 而不是在测试里手抄一份实现 —— 手抄的实现永远跟着测试一起变，
 * 源码改了它也发现不了。
 *
 * 背景：模型会把 RAG prompt 里的「若为「无」则忽略」中的「无」当成合法 ID，
 * 输出 `[[cite:无]]`。界面上于是出现一个点了没反应、悬停显示「引用 · 无」的幽灵角标。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { transformSync } from 'esbuild'

const here = dirname(fileURLToPath(import.meta.url))
const srcPath = resolve(here, '../src/core/domain/citations.ts')

let pass = 0
let fail = 0
function check(label, ok) {
  if (ok) {
    pass++
    console.log(`PASS  ${label}`)
  } else {
    fail++
    console.log(`FAIL  ${label}`)
  }
}

const src = readFileSync(srcPath, 'utf8')
const js = transformSync(src, { loader: 'ts', format: 'esm' }).code
// 去掉类型导入（esbuild 已处理），data: URL 模块可以直接执行
const mod = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'))

const { extractCitations, tokenizeInline, isValidCiteId, buildCitationContext } = mod

/* ---- isValidCiteId ---- */
check('空字符串无效', isValidCiteId('') === false)
check('「无」无效', isValidCiteId('无') === false)
check('「（无）」无效', isValidCiteId('（无）') === false)
check('none 无效', isValidCiteId('none') === false)
check('真实 ID 有效', isValidCiteId('5dc4aa0c8f53081cb04b880f5c2faefb') === true)
check('reason_0 有效', isValidCiteId('reason_0') === true)

/* ---- extractCitations 丢弃占位符 ---- */
const ctx = buildCitationContext([{ doc_id: 'abc', title: '真实文档' }], [])
const text = '这句有依据[[cite:abc]]，这句没有[[cite:无]]，这句也是[[cite:（无）]]。'
const map = extractCitations(text, ctx)
check('占位符不计入引用表', map.size === 1)
check('真实 ID 仍被识别', map.has('abc'))
check('真实 ID 序号从 1 开始', map.get('abc')?.index === 1)

/* ---- tokenizeInline 不产生占位符 token ---- */
const { tokens } = tokenizeInline(text, true)
const citeTokens = tokens.filter((t) => t.type === 'cite' || t.type === 'guide')
check('占位符标记不产生引用 token', citeTokens.length === 1)
check('留下的 token 是真实 ID', citeTokens[0]?.id === 'abc')

const joined = tokens.map((t) => (t.type === 'text' ? t.value : '')).join('')
check('正文不残留占位符标记', !joined.includes('无]'))
check('正文保留了正常文字', joined.includes('这句没有'))

/* ---- 不误伤正常内容 ---- */
const okText = '正常引用[[cite:abc]]结束'
const okTokens = tokenizeInline(okText, true)
check('正常引用仍生成 token', okTokens.tokens.filter((t) => t.type === 'cite').length === 1)

console.log(`\n${pass} pass / ${fail} fail`)
process.exit(fail === 0 ? 0 : 1)
