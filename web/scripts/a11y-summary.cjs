const { chromium } = require('playwright')
const { AxeBuilder } = require('@axe-core/playwright')
const BASE = 'http://127.0.0.1:8010/'
const VIEWS = ['#/', '#/records', '#/write', '#/trace', '#/retrieval']

;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 } })
  const p = await ctx.newPage()
  for (const hash of VIEWS) {
    await p.goto(BASE + hash, { waitUntil: 'networkidle' })
    await p.waitForTimeout(2200)
    const axe = await new AxeBuilder({ page: p })
      .withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze()
    const list = axe.violations.map(v => `${v.id}[${v.impact}]x${v.nodes.length}`)
    console.log(`${hash.padEnd(14)} total=${axe.violations.length}  ${list.join(' ')}`)
  }
  await b.close()
})()
