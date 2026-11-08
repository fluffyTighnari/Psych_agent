const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2800)

  const r = await p.evaluate(() => {
    const first = document.querySelector('.result-list .disc')
    const summary = first?.querySelector('.rc__summary')
    const chips = first?.querySelectorAll('.rc__chip').length ?? 0
    const cs = summary ? getComputedStyle(summary) : null
    return {
      cards: document.querySelectorAll('.result-list .disc').length,
      summaryVisible: cs ? cs.display !== 'none' && summary.getBoundingClientRect().height > 0 : false,
      summaryFont: cs?.fontSize,
      summaryText: summary?.textContent?.trim().slice(0, 50),
      chipsInCollapsed: chips,
      // 折叠态下能看到几条摘要
      visibleSummaries: [...document.querySelectorAll('.rr__summary, .rc__summary')]
        .filter(el => el.getBoundingClientRect().height > 0).length,
    }
  })
  await p.screenshot({ path: '../docs/_shots/batch-a-records-v2.png' })
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
