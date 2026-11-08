const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1500, height: 980 }, deviceScaleFactor: 2 })
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)

  // TurnTrace 特写
  const tt = await p.$('.tt')
  if (tt) await tt.screenshot({ path: '../docs/_shots/p2-turntrace.png' })

  // 展开大纲
  const toggle = await p.$('.rail-ticks__toggle')
  if (toggle) { await toggle.click(); await p.waitForTimeout(600) }
  const panel = await p.$('.rail-panel')
  if (panel) await panel.screenshot({ path: '../docs/_shots/p2-rail.png' })

  // 引用 chip 特写
  const cite = await p.$('.cite')
  if (cite) {
    const box = await cite.boundingBox()
    if (box) {
      await p.screenshot({
        path: '../docs/_shots/p2-cite.png',
        clip: { x: Math.max(0, box.x - 120), y: Math.max(0, box.y - 40), width: 360, height: 100 },
      })
    }
  }
  await b.close()
})()
