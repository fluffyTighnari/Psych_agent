const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 950 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  const r = {}

  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3500)

  // 1. 输入框聚焦淡红
  await p.click('.composer__input')
  await p.waitForTimeout(300)
  r.focus = await p.evaluate(() => {
    const cs = getComputedStyle(document.querySelector('.composer__box'))
    return { border: cs.borderColor, shadow: cs.boxShadow }
  })

  // 2. 引导模式未发首条时的 placeholder
  await p.evaluate(() => localStorage.clear())
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  const hasPicker = await p.$('.mode-card')
  if (hasPicker) {
    await p.click('.mode-card:nth-child(2)')
    await p.waitForTimeout(300)
  }
  r.guidedPlaceholder = await p.evaluate(() => ({
    mode: document.querySelector('.mode-card.is-active .mode-card__title')?.textContent?.trim(),
    placeholder: document.querySelector('.composer__input')?.placeholder,
  }))

  // 3. 滚轮平滑
  await p.waitForTimeout(2500)
  const box = await p.evaluate(() => {
    const c = document.querySelector('.gc__canvas')
    if (!c) return null
    const b = c.getBoundingClientRect()
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 }
  })
  if (box) {
    await p.mouse.move(box.x, box.y)
    const scales = []
    for (let i = 0; i < 6; i++) {
      await p.mouse.wheel(0, -100)
      await p.waitForTimeout(120)
      scales.push(await p.evaluate(() => document.querySelector('.gc__scale')?.textContent?.trim()))
    }
    r.wheelScales = scales
  }

  // 4. 图谱节点数 vs API 节点数
  await p.waitForTimeout(1200)
  r.graphSync = await p.evaluate(async () => {
    const res = await fetch('/graph/session-relation')
    const j = await res.json()
    return {
      apiNodes: j.data.nodes.length,
      domNodes: document.querySelectorAll('.gnode').length,
      labels: [...document.querySelectorAll('.glabel')].map(l => l.textContent),
    }
  })

  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
