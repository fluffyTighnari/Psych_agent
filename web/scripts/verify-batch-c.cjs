/** 批次C 验证：图谱拖宽折叠、文档标签分级、摘取展开与选区插入 */
const { chromium } = require('playwright')
const { AxeBuilder } = require('@axe-core/playwright')

;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1700, height: 1000 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  const r = {}

  // ---- 1. 图谱默认宽度（应为 380，不再是 340）----
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3500)

  r.graphDefault = await p.evaluate(() => {
    const pane = document.querySelector('.graph-pane')
    const stage = document.querySelector('.gc__stage')
    return {
      paneW: Math.round(pane?.getBoundingClientRect().width ?? 0),
      stageW: Math.round(stage?.getBoundingClientRect().width ?? 0),
      hasGrip: !!document.querySelector('.graph-pane__grip'),
    }
  })

  // ---- 2. 拖宽 ----
  const grip = await p.$('.graph-pane__grip')
  if (grip) {
    const box = await grip.boundingBox()
    await p.mouse.move(box.x + 4, box.y + 200)
    await p.mouse.down()
    await p.mouse.move(box.x - 120, box.y + 200, { steps: 10 })
    await p.mouse.up()
    await p.waitForTimeout(600)
  }
  r.afterDrag = await p.evaluate(() => ({
    paneW: Math.round(document.querySelector('.graph-pane')?.getBoundingClientRect().width ?? 0),
    stored: localStorage.getItem('psy:graph-width'),
  }))

  // ---- 3. 折叠与恢复 ----
  const collapseBtn = await p.$('.graph-pane button[aria-label="收起图谱"]')
  if (collapseBtn) { await collapseBtn.click(); await p.waitForTimeout(600) }
  r.collapsed = await p.evaluate(() => ({
    paneGone: !document.querySelector('.graph-pane'),
    restoreBar: !!document.querySelector('.graph-restore'),
  }))

  const restoreBar = await p.$('.graph-restore')
  if (restoreBar) { await restoreBar.click(); await p.waitForTimeout(800) }
  r.restored = await p.evaluate(() => ({
    paneBack: !!document.querySelector('.graph-pane'),
    paneW: Math.round(document.querySelector('.graph-pane')?.getBoundingClientRect().width ?? 0),
  }))

  // ---- 4. 文档标签分级（检查画布是否绘制）----
  r.labelGrading = await p.evaluate(() => {
    const c = document.querySelector('.gc__canvas')
    if (!c) return null
    const ctx = c.getContext('2d')
    const d = ctx.getImageData(0, 0, c.width, c.height).data
    let drawn = 0
    for (let i = 3; i < d.length; i += 4 * 53) if (d[i] > 0) drawn++
    return { drawn, hasAria: !!c.getAttribute('aria-label') }
  })
  await p.screenshot({ path: '../docs/_shots/batch-c-graph.png' })

  // ---- 5. 摘取面板 ----
  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  await p.click('button:has-text("从对话摘取")')
  await p.waitForTimeout(900)

  r.pickPanel = await p.evaluate(() => {
    const drawer = document.querySelector('.drawer-panel')
    if (!drawer) return { open: false }
    return {
      open: true,
      width: Math.round(drawer.getBoundingClientRect().width),
      candidates: drawer.querySelectorAll('.pick__item').length,
      hasExpandBtn: [...drawer.querySelectorAll('.pick__item button')].some(b => b.textContent.includes('展开全文')),
    }
  })

  // 展开全文
  const expandBtn = await p.$('.pick__item button:has-text("展开全文")')
  if (expandBtn) { await expandBtn.click(); await p.waitForTimeout(600) }
  r.expanded = await p.evaluate(() => {
    const full = document.querySelector('.pick__full')
    return {
      hasFull: !!full,
      fullFont: full?.querySelector('.pick__full-text') ? getComputedStyle(full.querySelector('.pick__full-text')).fontSize : null,
      fullLen: full?.querySelector('.pick__full-text')?.textContent?.length ?? 0,
      hint: full?.querySelector('.pick__full-hint')?.textContent?.trim().slice(0, 24),
    }
  })
  await p.screenshot({ path: '../docs/_shots/batch-c-pick.png' })
  await p.keyboard.press('Escape')
  await p.waitForTimeout(500)

  // ---- 6. 无障碍 ----
  const axe = await new AxeBuilder({ page: p }).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze()
  r.a11y = { violations: axe.violations.length, ids: axe.violations.map(v => v.id) }

  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
