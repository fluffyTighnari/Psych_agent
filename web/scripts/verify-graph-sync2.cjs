/** 验证：对话后图谱自动更新；总结后图谱刷新 */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 950 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })

  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3000)

  const before = await p.evaluate(() => document.querySelectorAll('.gnode').length)

  await p.fill('.composer__input', '我最近总是失眠，脑子里停不下来，想聊聊这件事。')
  await p.click('button:has-text("发送")')
  for (let i = 0; i < 200; i++) {
    await p.waitForTimeout(1000)
    const done = await p.evaluate(() => {
      const cs = [...document.querySelectorAll('.chain')]
      return cs.length > 0 && !cs[cs.length - 1].classList.contains('chain--running')
    })
    if (done) break
  }
  await p.waitForTimeout(3000)

  const afterChat = await p.evaluate(async () => {
    const res = await fetch('/graph/session-relation')
    const j = await res.json()
    return {
      api: j.data.nodes.length,
      dom: document.querySelectorAll('.gnode').length,
      labels: [...document.querySelectorAll('.glabel')].filter(l => !l.classList.contains('is-hidden')).map(l => l.textContent),
    }
  })

  // 总结
  await p.click('.view-head__actions button:has-text("一键总结")')
  for (let i = 0; i < 200; i++) {
    await p.waitForTimeout(1000)
    const t = await p.evaluate(() => document.querySelector('.toast')?.textContent?.trim() ?? '')
    if (t) break
  }
  const afterSummary = await p.evaluate(async () => {
    const res = await fetch('/graph/session-relation')
    const j = await res.json()
    return {
      api: j.data.nodes.length,
      dom: document.querySelectorAll('.gnode').length,
      toast: document.querySelector('.toast')?.textContent?.trim().slice(0, 40) ?? null,
    }
  })

  const stage = await p.$('.gc__stage')
  if (stage) await stage.screenshot({ path: '../docs/_shots/r6-graph-synced.png' })

  console.log(JSON.stringify({ before, afterChat, afterSummary, errors }, null, 2))
  await b.close()
})()
