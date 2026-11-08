const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 950 }, deviceScaleFactor: 3 })
  const p = await ctx.newPage()
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3000)

  const box = await p.evaluate(() => {
    const r = document.querySelector('.composer__box').getBoundingClientRect()
    return { x: r.x, y: r.y, w: r.width, h: r.height }
  })

  // 未聚焦
  const unfocused = await p.evaluate(() => {
    const cs = getComputedStyle(document.querySelector('.composer__box'))
    return { border: cs.border, shadow: cs.boxShadow }
  })
  await p.screenshot({ path: '../docs/_shots/diag-composer-unfocused.png', clip: { x: box.x - 4, y: box.y - 4, width: 260, height: 80 } })

  // 聚焦
  await p.click('.composer__input')
  await p.waitForTimeout(400)
  const focused = await p.evaluate(() => {
    const cs = getComputedStyle(document.querySelector('.composer__box'))
    return { border: cs.border, shadow: cs.boxShadow }
  })
  await p.screenshot({ path: '../docs/_shots/diag-composer-focused.png', clip: { x: box.x - 4, y: box.y - 4, width: 260, height: 80 } })

  console.log(JSON.stringify({ unfocused, focused }, null, 2))
  await b.close()
})()
