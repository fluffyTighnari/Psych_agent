const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 950 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()

  // 刻度轨浮层
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3500)
  const mark = await p.$('.rail-ticks .mark')
  if (mark) { await mark.hover(); await p.waitForTimeout(600) }
  const box = await p.evaluate(() => {
    const tip = document.querySelector('.rail-ticks__tip')
    if (!tip) return null
    const r = tip.getBoundingClientRect()
    return {
      x: Math.max(0, Math.round(r.x - 20)),
      y: Math.max(0, Math.round(r.y - 20)),
      width: Math.round(r.width + 60),
      height: Math.round(r.height + 40),
    }
  })
  if (box) await p.screenshot({ path: '../docs/_shots/r5-rail-tip.png', clip: box })

  // 编辑页底部
  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2200)
  await p.click('.cm-content')
  await p.keyboard.type('验证底部留白。')
  await p.waitForTimeout(2600)
  await p.screenshot({ path: '../docs/_shots/r5-write.png' })

  // 专注模式
  await p.click('button:has-text("专注")')
  await p.waitForTimeout(700)
  await p.screenshot({ path: '../docs/_shots/r5-focus.png' })
  await b.close()
})()
