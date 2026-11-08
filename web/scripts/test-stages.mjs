/**
 * 阶段映射覆盖测试。
 * 从后端源码提取的全部 stage 名都必须有正经映射，不能落到兜底。
 * 这个测试的意义：以后后端加新阶段时，即使开发者忘了改映射，
 * 也能在这里看到「哪些阶段还在裸奔」。
 */
import { readFileSync } from 'node:fs'
import { execSync } from 'node:child_process'

let pass = 0, fail = 0
const check = (cond, label, detail) => {
  if (cond) { pass++; console.log(`PASS  ${label}`) }
  else { fail++; console.log(`FAIL  ${label}${detail ? '\n   ' + detail : ''}`) }
}

// 从 stages.ts 源码里抽取 DEFS 的 key
const src = readFileSync('src/core/domain/stages.ts', 'utf8')
const defsBlock = src.slice(src.indexOf('const DEFS'), src.indexOf('export function resolveStage'))
const mapped = [...defsBlock.matchAll(/^\s{2}([a-z_]+):\s*\{/gm)].map(m => m[1])

// 从后端源码抽取全部 stage 名
let backendStages = []
try {
  const out = execSync(
    `grep -rhoE "stage=[\\"'][a-z_]+[\\"']" --include="*.py" ../core ../api`,
    { encoding: 'utf8' },
  )
  backendStages = [...new Set(out.split('\n').map(l => l.replace(/.*stage=["']|["']$/g, '')).filter(Boolean))]
} catch {
  console.log('SKIP  无法读取后端源码（不在仓库根目录运行时）')
}

check(mapped.length >= 25, `已映射阶段数 >= 25（实际 ${mapped.length}）`)

if (backendStages.length) {
  const missing = backendStages.filter(s => !mapped.includes(s))
  check(missing.length === 0, '后端全部 stage 都有映射', missing.length ? `未映射: ${missing.join(', ')}` : '')
  console.log(`\n后端 stage 共 ${backendStages.length} 个，前端已映射 ${mapped.length} 个`)
}

// 关键阶段必须有具体标题（不是原样输出）
const critical = ['classify_intent', 'session_init', 'tool_result', 'remediation', 'evaluate', 'session_save', 'guided_reasoning']
for (const s of critical) {
  check(mapped.includes(s), `关键阶段 ${s} 已映射`)
}

console.log(`\n${pass} pass / ${fail} fail`)
process.exit(fail === 0 ? 0 : 1)
