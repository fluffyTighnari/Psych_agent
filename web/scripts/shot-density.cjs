const { chromium } = require('playwright')
const views = [['#/', 'chat'], ['#/records', 'records'], ['#/write', 'write'], ['#/trace', 'trace'], ['#/retrieval', 'retrieval']]
;(async () => {
  const b = await chromium.launch()
  const p = await (await b.newContext({ viewport: { width: 1500, height: 950 }, deviceScaleFactor: 2 })).newPage()
  for (const [hash, name] of views) {
    await p.goto('http://127.0.0.1:8010/' + hash, { waitUntil: 'networkidle' })
    await p.waitForTimeout(2500)
    await p.screenshot({ path: `../docs/_shots/density-${name}.png` })
  }
  await b.close()
})()
