const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 950 }, deviceScaleFactor: 3 })
  const p = await ctx.newPage()
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3500)

  const g = await p.$('.gnode')
  if (g) { await g.hover(); await p.waitForTimeout(600) }

  const box = await p.evaluate(() => {
    const n = document.querySelector('.gnode')
    if (!n) return null
    const r = n.getBoundingClientRect()
    return { x: Math.max(0, Math.round(r.x - 30)), y: Math.max(0, Math.round(r.y - 30)), width: Math.round(r.width + 60), height: Math.round(r.height + 60) }
  })
  if (box) await p.screenshot({ path: '../docs/_shots/r6-halo.png', clip: box })
  await b.close()
})()
