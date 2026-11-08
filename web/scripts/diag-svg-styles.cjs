const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1600, height: 1000 } })
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(4000)

  const info = await p.evaluate(() => {
    const g = document.querySelector('.gnode')
    if (!g) return { none: true }
    const out = { children: [] }
    for (const el of g.querySelectorAll('*')) {
      const cs = getComputedStyle(el)
      out.children.push({
        tag: el.tagName,
        cls: el.getAttribute('class'),
        fill: cs.fill,
        stroke: cs.stroke,
        strokeWidth: cs.strokeWidth,
        opacity: cs.opacity,
        r: el.getAttribute('r'),
        d: (el.getAttribute('d') || '').slice(0, 40),
      })
    }
    const scaleG = g.querySelector('.gnode__glyph')
    out.glyphTransform = scaleG?.getAttribute('transform')
    out.nodeR = g.__nodeR
    return out
  })
  console.log(JSON.stringify(info, null, 2))
  await b.close()
})()
