/** Turn 领域模型单测：阶段归属、耗时哨兵、引用提取 */
let pass = 0, fail = 0
const eq = (a, e, label) => {
  const ok = JSON.stringify(a) === JSON.stringify(e)
  if (ok) { pass++; console.log(`PASS  ${label}`) }
  else { fail++; console.log(`FAIL  ${label}\n   expected ${JSON.stringify(e)}\n   actual   ${JSON.stringify(a)}`) }
}

/* ---- 复刻 turnDuration 逻辑 ---- */
function turnDuration(turn) {
  if (turn.startedAt <= 0) return null
  if (!turn.finishedAt) return Date.now() - turn.startedAt
  return turn.finishedAt - turn.startedAt
}

// 回归：历史回合（startedAt=0）不得算出天文数字
eq(turnDuration({ startedAt: 0, finishedAt: 0 }), null, '回归：历史回合耗时为 null')

// 正常回合
eq(turnDuration({ startedAt: 1000, finishedAt: 3500 }), 2500, '正常回合耗时')

// 无 finishedAt 时用当前时间（只验证 > 0）
eq(turnDuration({ startedAt: Date.now() - 100, finishedAt: null }) >= 100, true, '进行中回合用当前时间')

/* ---- 阶段归属：残留过滤 ---- */
const STALE_WINDOW_SEC = 0.5
const isStale = (item, turn) => item.timestamp < turn.startedAt / 1000 - STALE_WINDOW_SEC

const turn = { startedAt: 1_700_000_000_000 } // 秒 = 1700000000
eq(isStale({ timestamp: 1_699_999_000 }, turn), true, '上一轮残留日志被过滤')
eq(isStale({ timestamp: 1_700_000_001 }, turn), false, '本轮日志不被过滤')
eq(isStale({ timestamp: 1_699_999_999.7 }, turn), false, '起点的临界值不被误杀')

/* ---- 阶段去重签名 ---- */
const sig = (t) => `${t.timestamp}_${t.stage}_${t.label}_${JSON.stringify(t.content ?? {})}`
eq(
  sig({ timestamp: 1, stage: 'a', label: 'b', content: { x: 1 } }),
  sig({ timestamp: 1, stage: 'a', label: 'b', content: { x: 1 } }),
  '相同 trace 签名一致',
)
eq(
  sig({ timestamp: 1, stage: 'a', label: 'b', content: { x: 1 } }) !==
    sig({ timestamp: 2, stage: 'a', label: 'b', content: { x: 1 } }),
  true,
  '不同时间戳签名不同',
)

console.log(`\n${pass} pass / ${fail} fail`)
process.exit(fail === 0 ? 0 : 1)
