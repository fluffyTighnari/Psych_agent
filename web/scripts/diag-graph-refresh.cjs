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

  const before = await p.evaluate(() => ({
    nodes: document.querySelectorAll('.gnode').length,
    nodeIds: [...document.querySelectorAll('.gnode')].map(g => g.dataset.nodeId),
    labels: document.querySelectorAll('.glabel').length,
  }))

  // 触发 graph.load()
  const afterLoad = await p.evaluate(async () => {
    const r = await fetch('/graph/session-relation')
    const j = await r.json()
    return { apiNodes: j.data.nodes.length, apiIds: j.data.nodes.map(n => n.id) }
  })

  // 点刷新
  await p.click('.graph-pane__head button[aria-label="收起图谱"]').catch(() => {})
  await p.waitForTimeout(400)
  const restored = await p.$('.graph-restore')
  if (restored) { await restored.click(); await p.waitForTimeout(1200) }

  const after = await p.evaluate(() => ({
    nodes: document.querySelectorAll('.gnode').length,
    labels: document.querySelectorAll('.glabel').length,
    svgExists: !!document.querySelector('.graph-svg'),
  }))

  console.log(JSON.stringify({ before, afterLoad, after, errors }, null, 2))
  await b.close()
})()
