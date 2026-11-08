const { chromium } = require('playwright')
const { AxeBuilder } = require('@axe-core/playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 } })
  const p = await ctx.newPage()
  await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  const axe = await new AxeBuilder({ page: p })
    .withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze()
  for (const v of axe.violations) {
    console.log(`\n== ${v.id} (${v.impact}) ==`)
    for (const n of v.nodes) {
      console.log(`  target: ${n.target.join(' ')}`)
      console.log(`  ${(n.failureSummary || '').replace(/\n/g, ' | ').slice(0, 220)}`)
    }
  }
  await b.close()
})()
