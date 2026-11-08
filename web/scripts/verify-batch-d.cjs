/** 批次D 验证：连接列表、拉取模型、槽位选择、保存 */
const { chromium } = require('playwright')
const { AxeBuilder } = require('@axe-core/playwright')

;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  const r = {}

  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)

  // 打开模型设置
  await p.click('button:has-text("模型设置")')
  await p.waitForTimeout(1500)

  r.drawer = await p.evaluate(() => {
    const d = document.querySelector('.drawer-panel')
    if (!d) return { open: false }
    return {
      open: true,
      title: d.querySelector('.drawer-panel__title')?.textContent?.trim(),
      sections: [...d.querySelectorAll('.sec__title')].map(x => x.textContent.trim()),
      connections: [...d.querySelectorAll('.conn__name')].map(x => x.textContent.trim()),
      kinds: [...d.querySelectorAll('.conn__kind')].map(x => x.textContent.trim()),
      hasFetchBtn: [...d.querySelectorAll('button')].some(x => x.textContent.includes('拉取模型')),
      slotCount: d.querySelectorAll('.slot').length,
      hasAdvanced: [...d.querySelectorAll('button')].some(x => x.textContent.includes('高级')),
      advancedCollapsed: d.querySelector('.advanced') ? getComputedStyle(d.querySelector('.advanced')).display === 'none' : null,
    }
  })

  // 拉取 DeepSeek 模型（真实网络）
  const fetchBtn = await p.$('.conn:has-text("DeepSeek") button:has-text("拉取模型")')
  if (fetchBtn) {
    await fetchBtn.click()
    await p.waitForTimeout(12000)
  }
  r.afterFetch = await p.evaluate(() => ({
    countText: [...document.querySelectorAll('.conn__count')].map(x => x.textContent.trim()),
    slotSelects: document.querySelectorAll('.slot select').length,
    options: (() => {
      const sel = document.querySelector('.slot select')
      if (!sel) return []
      return [...sel.querySelectorAll('option')].slice(0, 6).map(o => o.textContent.trim())
    })(),
  }))

  // 展开高级区
  const advBtn = await p.$('.advanced-toggle')
  if (advBtn) { await advBtn.click(); await p.waitForTimeout(500) }
  r.advanced = await p.evaluate(() => {
    const a = document.querySelector('.advanced')
    return { visible: a ? getComputedStyle(a).display !== 'none' : false }
  })

  await p.screenshot({ path: '../docs/_shots/batch-d-model.png' })

  // 无障碍
  const axe = await new AxeBuilder({ page: p }).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze()
  r.a11y = { violations: axe.violations.length, ids: axe.violations.map(v => v.id) }

  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
