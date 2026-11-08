const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1680, height: 1000 } })
  const logs = []
  p.on('console', m => logs.push(m.type() + ': ' + m.text()))
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(5000)

  const info = await p.evaluate(() => {
    const c = document.querySelector('canvas')
    const rect = c.getBoundingClientRect()
    return {
      rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
      // 检查 Inspector 元素
      insExists: !!document.querySelector('.ins'),
      // 图谱面板尺寸
      paneRect: (() => { const g = document.querySelector('.graph-pane'); if (!g) return null; const r = g.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) } })(),
      stageRect: (() => { const g = document.querySelector('.gc__stage'); if (!g) return null; const r = g.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) } })(),
    }
  })
  console.log(JSON.stringify({ info, logs: logs.slice(-5) }, null, 2))
  await b.close()
})()
