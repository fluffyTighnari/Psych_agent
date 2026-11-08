const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1500, height: 950 } })
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3500)
  const g = await p.$('.gnode')
  if (g) { await g.hover(); await p.waitForTimeout(500) }

  const info = await p.evaluate(() => {
    const g = document.querySelector('.gnode')
    if (!g) return { none: true }
    return {
      html: g.outerHTML.slice(0, 1200),
      children: [...g.querySelectorAll('*')].map(el => {
        const cs = getComputedStyle(el)
        return {
          tag: el.tagName,
          cls: el.getAttribute('class'),
          fill: cs.fill,
          opacity: cs.opacity,
          r: el.getAttribute('r'),
          d: (el.getAttribute('d') || '').slice(0, 50),
        }
      }),
    }
  })
  console.log(JSON.stringify(info, null, 2))
  await b.close()
})()
