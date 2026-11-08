const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
  await p.goto('http://127.0.0.1:8010/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(1200)
  await p.click('button:has-text("模型设置")')
  await p.waitForTimeout(600)
  const info = await p.evaluate(() => {
    const foot = document.querySelector('.drawer-panel__foot')
    if (!foot) return { noFoot: true }
    const btns = [...foot.querySelectorAll('button')].map(b => ({
      text: b.textContent.trim(),
      w: Math.round(b.getBoundingClientRect().width),
      h: Math.round(b.getBoundingClientRect().height),
      visible: b.getBoundingClientRect().width > 0,
      disabled: b.disabled,
    }))
    const r = foot.getBoundingClientRect()
    return { btnCount: btns.length, btns, footRect: { w: Math.round(r.width), h: Math.round(r.height) } }
  })
  console.log(JSON.stringify(info, null, 2))
  await b.close()
})()
