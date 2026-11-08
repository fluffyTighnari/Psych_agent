/** 批次A 验证：字体、记录页滚动、编辑页红线与专注模式 */
const { chromium } = require('playwright')
const { AxeBuilder } = require('@axe-core/playwright')

;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  const r = {}

  // ---- 1. 字体令牌 ----
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  r.tokens = await p.evaluate(() => {
    const cs = getComputedStyle(document.documentElement)
    const v = n => cs.getPropertyValue(n).trim()
    return {
      fs2xs: v('--fs-2xs'), fsXs: v('--fs-xs'), fsSm: v('--fs-sm'),
      fsBase: v('--fs-base'), lhBody: v('--lh-body'),
      bodySmoothing: getComputedStyle(document.body).webkitFontSmoothing,
    }
  })
  r.bodyFontActual = await p.evaluate(() => getComputedStyle(document.body).fontSize)

  // ---- 2. 记录页滚动 ----
  await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  r.records = await p.evaluate(() => {
    const view = document.querySelector('.app-view')
    const results = document.querySelector('.results')
    const summary = document.querySelector('.rc__summary')
    const toggle = document.querySelector('.filters-toggle')
    return {
      viewScrollable: view ? view.scrollHeight > view.clientHeight + 2 : false,
      viewOverflowY: view ? getComputedStyle(view).overflowY : null,
      resultsOverflowY: results ? getComputedStyle(results).overflowY : null,
      summaryFontSize: summary ? getComputedStyle(summary).fontSize : null,
      hasToggle: !!toggle,
      toggleExpanded: toggle?.getAttribute('aria-expanded'),
      filtersHidden: (() => {
        const f = document.querySelector('#records-filters')
        return f ? getComputedStyle(f).display === 'none' : null
      })(),
    }
  })

  // 展开筛选
  const toggle = await p.$('.filters-toggle')
  if (toggle) { await toggle.click(); await p.waitForTimeout(400) }
  r.afterExpand = await p.evaluate(() => ({
    toggleExpanded: document.querySelector('.filters-toggle')?.getAttribute('aria-expanded'),
    filtersVisible: (() => {
      const f = document.querySelector('#records-filters')
      return f ? getComputedStyle(f).display !== 'none' : null
    })(),
  }))
  await p.screenshot({ path: '../docs/_shots/batch-a-records.png' })

  // ---- 3. 编辑页红线 ----
  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  await p.click('.cm-content')
  await p.keyboard.type('验证焦点态')
  await p.waitForTimeout(500)
  r.editorFocus = await p.evaluate(() => {
    const ed = document.querySelector('.md-editor')
    const cs = getComputedStyle(ed)
    return {
      boxShadow: cs.boxShadow,
      borderColor: cs.borderColor,
      hasOuterGlow: cs.boxShadow !== 'none' && cs.boxShadow.includes('rgba(194, 74, 46'),
    }
  })
  const ed = await p.$('.md-editor')
  if (ed) await ed.screenshot({ path: '../docs/_shots/batch-a-editor.png' })

  // ---- 4. 专注模式居中 ----
  await p.click('button:has-text("专注")')
  await p.waitForTimeout(800)
  r.focusMode = await p.evaluate(() => {
    const wrap = document.querySelector('.editor-wrap')
    const view = document.querySelector('.app-view')
    const rail = document.querySelector('.rail')
    const wrapRect = wrap?.getBoundingClientRect()
    const viewRect = view?.getBoundingClientRect()
    const leftGap = wrapRect && viewRect ? wrapRect.left - viewRect.left : 0
    const rightGap = wrapRect && viewRect ? viewRect.right - wrapRect.right : 0
    return {
      railHidden: !rail,
      wrapW: Math.round(wrapRect?.width ?? 0),
      viewW: Math.round(viewRect?.width ?? 0),
      ratio: viewRect ? Math.round((wrapRect.width / viewRect.width) * 100) : 0,
      leftGap: Math.round(leftGap),
      rightGap: Math.round(rightGap),
      centered: Math.abs(leftGap - rightGap) < 8,
    }
  })
  await p.screenshot({ path: '../docs/_shots/batch-a-focus.png' })

  // ---- 5. 无障碍仍为 0 ----
  const axe = await new AxeBuilder({ page: p }).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze()
  r.a11y = { violations: axe.violations.length, serious: axe.violations.filter(v => v.impact === 'serious' || v.impact === 'critical').length }

  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
