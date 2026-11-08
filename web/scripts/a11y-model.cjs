const { chromium } = require('playwright')
const { AxeBuilder } = require('@axe-core/playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 } })
  const p = await ctx.newPage()
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  await p.click('button:has-text("模型设置")')
  await p.waitForTimeout(1200)
  const axe = await new AxeBuilder({ page: p }).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze()
  for (const v of axe.violations) {
    console.log(`== ${v.id} ==`)
    for (const n of v.nodes.slice(0, 3)) {
      console.log(`  ${n.target.join(' ')}`)
      console.log(`  ${(n.failureSummary || '').replace(/\n/g, ' | ').slice(0, 220)}`)
    }
  }
  await b.close()
})()
