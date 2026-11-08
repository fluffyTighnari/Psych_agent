const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 3 })
  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2200)
  await p.click('.cm-content')
  await p.keyboard.type('查')
  await p.waitForTimeout(400)

  const info = await p.evaluate(() => {
    const results = []
    // 遍历所有可能与左边缘相交的元素
    const all = document.querySelectorAll('.md-editor, .md-editor *')
    for (const el of all) {
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) continue
      const hasRed =
        cs.borderLeftColor.includes('194, 74, 46') ||
        cs.backgroundColor.includes('194, 74, 46') ||
        cs.boxShadow.includes('194, 74, 46') ||
        cs.outlineColor.includes('194, 74, 46')
      if (hasRed) {
        results.push({
          cls: el.className?.toString().slice(0, 40),
          tag: el.tagName,
          borderLeft: cs.borderLeft,
          bg: cs.backgroundColor,
          shadow: cs.boxShadow.slice(0, 60),
          outline: cs.outline,
          rectLeft: Math.round(r.left - document.querySelector('.md-editor').getBoundingClientRect().left),
          width: Math.round(r.width),
        })
      }
    }
    return { count: results.length, items: results }
  })
  console.log(JSON.stringify(info, null, 2))
  await b.close()
})()
