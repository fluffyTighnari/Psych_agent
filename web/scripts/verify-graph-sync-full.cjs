/** 多节点场景：发消息 → 图谱应出现 document 节点；总结后应刷新且不清空 */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 950 } })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  const r = {}

  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3000)

  const before = await p.evaluate(async () => {
    const res = await fetch('/graph/session-relation')
    const j = await res.json()
    return { api: j.data.nodes.length, dom: document.querySelectorAll('.gnode').length }
  })

  // 发消息触发检索（会产生 document 节点）
  await p.fill('.composer__input', '我总是很在意别人的评价，开会不敢发言，怎么调整？')
  await p.click('button:has-text("发送")')
  for (let i = 0; i < 200; i++) {
    await p.waitForTimeout(1000)
    const done = await p.evaluate(() => {
      const cs = [...document.querySelectorAll('.chain')]
      return cs.length > 0 && !cs[cs.length - 1].classList.contains('chain--running')
    })
    if (done) break
  }
  await p.waitForTimeout(2500)

  // 刷新图谱（对话后 store 里 graph 数据未自动重载）
  const refreshBtn = await p.$('.graph-pane__head button[aria-label="收起图谱"]')
  if (refreshBtn) { await refreshBtn.click(); await p.waitForTimeout(500) }
  const restore = await p.$('.graph-restore')
  if (restore) { await restore.click(); await p.waitForTimeout(2000) }

  const afterChat = await p.evaluate(async () => {
    const res = await fetch('/graph/session-relation')
    const j = await res.json()
    return { api: j.data.nodes.length, dom: document.querySelectorAll('.gnode').length }
  })

  // 一键总结
  await p.click('.view-head__actions button:has-text("一键总结")')
  await p.waitForTimeout(4000)
  const afterSummary = await p.evaluate(async () => {
    const res = await fetch('/graph/session-relation')
    const j = await res.json()
    return {
      api: j.data.nodes.length,
      dom: document.querySelectorAll('.gnode').length,
      toast: document.querySelector('.toast')?.textContent?.trim().slice(0, 40) ?? null,
    }
  })

  console.log(JSON.stringify({ before, afterChat, afterSummary, errors }, null, 2))
  await b.close()
})()
