const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 950 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2800)
  await p.screenshot({ path: '../docs/_shots/layers-records.png' })

  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3500)
  await p.screenshot({ path: '../docs/_shots/layers-chat.png' })

  // 表面亮度阶梯实测
  const ladder = await p.evaluate(() => {
    const cs = getComputedStyle(document.documentElement)
    const v = n => cs.getPropertyValue(n).trim()
    return {
      base: v('--surface'),
      card: v('--surface-raised'),
      sunken: v('--surface-sunken'),
      overlay: v('--surface-overlay'),
      borderSoft: v('--border-soft'),
      ef1: v('--ef-1').slice(0, 50),
    }
  })
  console.log(JSON.stringify(ladder, null, 2))
  await b.close()
})()
