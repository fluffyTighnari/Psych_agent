/** P6 最终验证：根挂载、全视图、无障碍、键盘可达 */
const { chromium } = require('playwright')
const { AxeBuilder } = require('@axe-core/playwright')

const BASE = 'http://127.0.0.1:8010/'
const VIEWS = [
  { hash: '#/', name: '主对话' },
  { hash: '#/records', name: '过往记录' },
  { hash: '#/write', name: '码字编辑' },
  { hash: '#/trace', name: '流程日志' },
  { hash: '#/retrieval', name: '检索调试' },
]

;(async () => {
  const browser = await chromium.launch()
  const context = await browser.newContext({ viewport: { width: 1500, height: 1000 } })
  const page = await context.newPage()
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))
  const failed = []
  page.on('response', r => { if (r.status() >= 400) failed.push(r.status() + ' ' + r.url()) })

  const r = { views: [], a11y: {} }

  for (const v of VIEWS) {
    await page.goto(BASE + v.hash, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2200)

    const info = await page.evaluate(() => ({
      h2: document.querySelector('.view-head__title h2')?.textContent?.trim()
        || document.querySelector('.focus-bar') ? '(write focus?)' : null,
      title: document.title,
      hasApp: !!document.querySelector('.app-shell'),
      hasRail: !!document.querySelector('.rail'),
      railActive: document.querySelector('.rail__item.is-active')?.textContent?.trim(),
      hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    }))
    r.views.push({ name: v.name, ...info })

    const axe = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    r.a11y[v.name] = {
      violations: axe.violations.length,
      serious: axe.violations.filter(x => x.impact === 'serious' || x.impact === 'critical').length,
    }
  }

  // 键盘可达：Tab 遍历一圈
  await page.goto(BASE + '#/', { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  const trail = []
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press('Tab')
    await page.waitForTimeout(160)
    trail.push(await page.evaluate(() => {
      const a = document.activeElement
      if (!a || a === document.body) return null
      const cs = getComputedStyle(a)
      return {
        tag: a.tagName.toLowerCase(),
        text: (a.textContent || '').trim().slice(0, 8),
        ring: !cs.boxShadow.startsWith('rgba(0, 0, 0, 0) 0px 0px 0px 0px'),
      }
    }))
  }
  r.keyboard = { focusables: trail.filter(Boolean).length, allRinged: trail.filter(Boolean).every(t => t.ring) }

  await page.screenshot({ path: '../docs/_shots/p6-final.png' })

  r.errors = errors
  r.failedRequests = failed
  console.log(JSON.stringify(r, null, 2))
  await browser.close()
})()
