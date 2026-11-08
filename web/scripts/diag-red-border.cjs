const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 950 }, deviceScaleFactor: 3 })
  const p = await ctx.newPage()
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3000)
  await p.click('.composer__input')
  await p.waitForTimeout(400)

  const found = await p.evaluate(() => {
    const out = []
    const root = document.querySelector('.composer')
    if (!root) return out
    for (const el of [root, ...root.querySelectorAll('*')]) {
      const cs = getComputedStyle(el)
      const hex = v => v
      const isRed = (str) => /194,\s*74,\s*46|162,\s*56,\s*32|226,\s*179,\s*163/.test(str)
      const hit = []
      if (isRed(cs.borderTopColor)) hit.push('borderTop:' + cs.borderTopColor)
      if (isRed(cs.borderBottomColor)) hit.push('borderBottom:' + cs.borderBottomColor)
      if (isRed(cs.borderLeftColor)) hit.push('borderLeft:' + cs.borderLeftColor)
      if (isRed(cs.boxShadow)) hit.push('shadow:' + cs.boxShadow.slice(0, 70))
      if (isRed(cs.outlineColor) && cs.outlineStyle !== 'none') hit.push('outline:' + cs.outline)
      if (hit.length) out.push({ cls: el.className?.toString().slice(0, 40), tag: el.tagName, hit })
    }
    return out
  })
  console.log(JSON.stringify(found, null, 2))
  await b.close()
})()
