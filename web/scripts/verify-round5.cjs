const { chromium } = require('playwright')
const { AxeBuilder } = require('@axe-core/playwright')

async function withPage(fn, w = 1500, h = 1000) {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  try { return { ...(await fn(p)), errors } } finally { await b.close() }
}

;(async () => {
  const out = {}

  // 1. 图谱面板总结键已删
  out.graphPane = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
    await p.waitForTimeout(3500)
    return await p.evaluate(() => {
      const pane = document.querySelector('.graph-pane')
      const btns = [...(pane?.querySelectorAll('.graph-pane__head button') ?? [])]
      return {
        headButtons: btns.map(b => b.textContent.trim() || b.getAttribute('aria-label')),
        hasSummaryInPane: btns.some(b => b.textContent.includes('总结')),
        hasSummaryInHeader: [...document.querySelectorAll('.view-head__actions button')]
          .some(b => b.textContent.includes('总结')),
      }
    })
  })

  // 2. Inspector 点击外部收回
  out.inspector = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
    await p.waitForTimeout(3500)
    await p.evaluate(() => {
      const d = document.querySelector('.gc__a11y')
      if (d) d.open = true
    })
    await p.waitForTimeout(300)
    const item = await p.$('.gc__a11y-item')
    if (item) { await item.click({ force: true }); await p.waitForTimeout(700) }
    const opened = await p.evaluate(() => !!document.querySelector('.ins'))
    // 点对话区空白
    await p.mouse.click(300, 400)
    await p.waitForTimeout(600)
    const closed = await p.evaluate(() => !document.querySelector('.ins'))
    return { opened, closedOnOutside: closed }
  })

  // 3. 刻度轨浮层宽度
  out.rail = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
    await p.waitForTimeout(3500)
    const mark = await p.$('.rail-ticks .mark')
    if (mark) { await mark.hover(); await p.waitForTimeout(500) }
    return await p.evaluate(() => {
      const tip = document.querySelector('.rail-ticks__tip')
      if (!tip) return { noTip: true }
      const r = tip.getBoundingClientRect()
      const cs = getComputedStyle(tip)
      return {
        width: Math.round(r.width),
        height: Math.round(r.height),
        oneLine: r.height < 40,
        text: tip.textContent.trim().slice(0, 40),
        whiteSpace: cs.whiteSpace,
      }
    })
  })

  // 4. 编辑页：专注模式只有一个状态 + 底部留白
  out.write = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
    await p.waitForTimeout(2200)
    await p.click('.cm-content')
    await p.keyboard.type('验证留白与状态')
    await p.waitForTimeout(2800)

    const normal = await p.evaluate(() => {
      const actions = document.querySelector('.actions')
      const wrap = document.querySelector('.editor-wrap')
      const r = actions?.getBoundingClientRect()
      const w = wrap?.getBoundingClientRect()
      return {
        gapBelowEditor: r && w ? Math.round(r.top - (w.top + w.height)) : null,
        statusCount: document.querySelectorAll('.meta-bar__state, .meta-bar__warn').length,
      }
    })

    await p.click('button:has-text("专注")')
    await p.waitForTimeout(700)
    const focus = await p.evaluate(() => ({
      v: null,
      statusInBar: document.querySelectorAll('.focus-bar__state').length,
      barButtons: [...document.querySelectorAll('.focus-bar button')].map(b => b.textContent.trim()),
    }))
    return { normal, focus }
  })

  // 5. weekly 标题无 .md
  out.titles = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
    await p.waitForTimeout(2800)
    const labels = await p.evaluate(() =>
      [...document.querySelectorAll('.result-list .disc__label')].map(x => x.textContent.trim()))
    return {
      total: labels.length,
      withMd: labels.filter(t => t.endsWith('.md')).length,
      samples: labels.slice(0, 5),
    }
  })

  // 6. 无障碍
  out.a11y = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
    await p.waitForTimeout(2500)
    const axe = await new AxeBuilder({ page: p }).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze()
    return { violations: axe.violations.length, ids: axe.violations.map(v => v.id) }
  })

  console.log(JSON.stringify(out, null, 2))
})()
