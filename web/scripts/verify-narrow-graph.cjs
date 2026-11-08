const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1000, height: 900 } })
  const p = await ctx.newPage()
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3500)
  const r = await p.evaluate(() => {
    const pane = document.querySelector('.graph-pane')
    return {
      paneExists: !!pane,
      isOverlay: pane?.classList.contains('is-overlay') ?? false,
      paneW: Math.round(pane?.getBoundingClientRect().width ?? 0),
      position: pane ? getComputedStyle(pane).position : null,
      hasGrip: !!document.querySelector('.graph-pane__grip'),
    }
  })
  console.log(JSON.stringify(r, null, 2))
  await p.screenshot({ path: '../docs/_shots/batch-c-narrow.png' })
  await b.close()
})()
