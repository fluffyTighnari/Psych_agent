const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 950 } })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })

  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3500)

  // 先发一条消息产生图谱数据
  await p.fill('.composer__input', '我最近工作压力很大，总是睡不好，想聊聊。')
  await p.click('button:has-text("发送")')
  for (let i = 0; i < 180; i++) {
    await p.waitForTimeout(1000)
    const done = await p.evaluate(() => {
      const cs = [...document.querySelectorAll('.chain')]
      return cs.length > 0 && !cs[cs.length - 1].classList.contains('chain--running')
    })
    if (done) break
  }
  await p.waitForTimeout(1500)

  const beforeSummary = await p.evaluate(() => ({
    nodes: document.querySelectorAll('.gnode').length,
    labels: [...document.querySelectorAll('.glabel')].map(l => l.textContent),
  }))

  // 点一键总结
  await p.click('.view-head__actions button:has-text("一键总结")')
  await p.waitForTimeout(3000)
  const toast = await p.evaluate(() => document.querySelector('.toast')?.textContent?.trim().slice(0, 50) ?? null)
  await p.waitForTimeout(2500)

  const afterSummary = await p.evaluate(() => ({
    nodes: document.querySelectorAll('.gnode').length,
    labels: [...document.querySelectorAll('.glabel')].map(l => l.textContent),
  }))
  const apiAfter = await p.evaluate(async () => {
    const r = await fetch('/graph/session-relation')
    const j = await r.json()
    return { nodes: j.data.nodes.length, types: j.data.nodes.map(n => n.type) }
  })

  console.log(JSON.stringify({ beforeSummary, toast, afterSummary, apiAfter, errors }, null, 2))
  await b.close()
})()
