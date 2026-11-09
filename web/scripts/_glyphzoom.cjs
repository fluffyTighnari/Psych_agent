const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await (await b.newContext({ viewport: { width: 1500, height: 950 }, deviceScaleFactor: 2 })).newPage()
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2800)

  // 给图谱造出多种节点：发一轮消息后总结，或直接看现有
  const info = await p.evaluate(() => {
    const nodes = [...document.querySelectorAll('.gnode')]
    return nodes.map((n) => ({
      cls: n.getAttribute('class'),
      box: (() => { const r = n.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)] })(),
    }))
  })
  console.log('当前节点:', JSON.stringify(info))

  const pane = await p.$('.graph-pane')
  if (pane) await pane.screenshot({ path: '../docs/_shots/glyph-current-100.png' })

  // 放大到 3x
  const canvas = await p.$('.gc__canvas')
  if (canvas) {
    const cb = await canvas.boundingBox()
    await p.mouse.move(cb.x + cb.width / 2, cb.y + cb.height / 2)
    for (let i = 0; i < 30; i++) {
      await p.mouse.wheel(0, -200)
      await p.waitForTimeout(30)
    }
    await p.waitForTimeout(500)
    const scale = await p.evaluate(() => document.querySelector('.gc__scale')?.textContent)
    console.log('放大后:', scale)
    if (pane) await pane.screenshot({ path: '../docs/_shots/glyph-current-max.png' })
  }
  await b.close()
})()
