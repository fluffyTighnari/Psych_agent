const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1680, height: 1000 }, deviceScaleFactor: 2 })
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3000)

  const r = {}
  r.collapsed = await p.evaluate(() => {
    const c = document.querySelector('.chain')
    if (!c) return null
    return {
      summary: c.querySelector('.chain__text')?.textContent?.trim(),
      badge: c.querySelector('.chain__badge')?.textContent?.trim() ?? null,
      time: c.querySelector('.chain__time')?.textContent?.trim() ?? null,
      stepsVisible: !!c.querySelector('.chain__steps'),
      ariaExpanded: c.querySelector('.chain__summary')?.getAttribute('aria-expanded'),
    }
  })

  // 展开
  const btn = await p.$('.chain__summary')
  if (btn) { await btn.click(); await p.waitForTimeout(500) }

  r.expanded = await p.evaluate(() => {
    const c = document.querySelector('.chain')
    return {
      stepsVisible: !!c.querySelector('.chain__steps'),
      ariaExpanded: c.querySelector('.chain__summary')?.getAttribute('aria-expanded'),
      steps: [...c.querySelectorAll('.chain__step')].map(s => ({
        name: s.querySelector('.chain__name')?.textContent?.trim(),
        detail: s.querySelector('.chain__detail')?.textContent?.trim() ?? null,
        dur: s.querySelector('.chain__dur')?.textContent?.trim() ?? null,
      })),
    }
  })

  // 执行链特写
  const chain = await p.$('.chain')
  if (chain) await chain.screenshot({ path: '../docs/_shots/p3-chain.png' })

  // 图谱面板特写
  const pane = await p.$('.graph-pane')
  if (pane) await pane.screenshot({ path: '../docs/_shots/p3-graph-pane.png' })

  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
