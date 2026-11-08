const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 3 })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })

  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(4000)

  const r = await p.evaluate(() => {
    const svg = document.querySelector('.graph-svg')
    if (!svg) return { noSvg: true }
    const nodes = [...svg.querySelectorAll('.gnode')]
    return {
      hasSvg: true,
      nodeCount: nodes.length,
      types: nodes.map(g => [...g.classList].find(c => c.startsWith('gnode--'))),
      hasLinks: !!svg.querySelector('.glink'),
      pathLens: nodes.map(g => {
        const path = g.querySelector('.gnode__stroke')
        return path ? path.getAttribute('d').length : 0
      }),
      // 每个节点是否有 title（无障碍）
      hasTitles: nodes.every(g => !!g.querySelector('title')),
      labels: svg.querySelectorAll('.glabel').length,
    }
  })

  // 节点区域截图
  const stage = await p.$('.gc__stage')
  if (stage) await stage.screenshot({ path: '../docs/_shots/svg-graph-light.png' })

  // hover 一个节点
  const firstNode = await p.$('.gnode')
  if (firstNode) {
    await firstNode.hover()
    await p.waitForTimeout(500)
  }
  const hoverState = await p.evaluate(() => {
    const g = document.querySelector('.gnode')
    const halo = g?.querySelector('.gnode__halo')
    return {
      cls: g?.getAttribute('class'),
      haloOpacity: halo ? getComputedStyle(halo).opacity : null,
      haloR: halo?.getAttribute('r'),
    }
  })
  if (stage) await stage.screenshot({ path: '../docs/_shots/svg-graph-hover.png' })

  // 暗色
  await p.evaluate(() => document.querySelector('.graph-svg')?.setAttribute('data-theme', 'dark'))
  await p.evaluate(() => {
    const stage = document.querySelector('.gc__stage')
    if (stage) stage.style.background = '#1c1917'
  })
  await p.waitForTimeout(500)
  if (stage) await stage.screenshot({ path: '../docs/_shots/svg-graph-dark.png' })

  const darkState = await p.evaluate(() => {
    const svg = document.querySelector('.graph-svg')
    const stroke = svg?.querySelector('.gnode__stroke')
    return {
      strokeColor: stroke ? getComputedStyle(stroke).stroke : null,
      hasDarkClass: svg?.getAttribute('data-theme'),
    }
  })

  // 3x 缩放清晰度：放大后截图
  await p.evaluate(() => document.querySelector('.graph-svg')?.removeAttribute('data-theme'))
  await p.evaluate(() => { const s = document.querySelector('.gc__stage'); if (s) s.style.background = '' })
  const zoomIn = await p.$('.gc__ctl[aria-label="放大"]')
  for (let i = 0; i < 5; i++) { if (zoomIn) { await zoomIn.click(); await p.waitForTimeout(200) } }
  await p.waitForTimeout(800)
  if (stage) await stage.screenshot({ path: '../docs/_shots/svg-graph-zoom3x.png' })

  const zoomState = await p.evaluate(() => ({
    scaleText: document.querySelector('.gc__scale')?.textContent?.trim(),
    labelScale: (() => {
      const l = document.querySelector('.glabel')
      const t = l?.getAttribute('transform') || ''
      const m = t.match(/scale\(([\d.]+)\)/)
      return m ? m[1] : null
    })(),
  }))

  console.log(JSON.stringify({ ...r, hoverState, darkState, zoomState, errors }, null, 2))
  await b.close()
})()
