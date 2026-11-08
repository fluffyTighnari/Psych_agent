/**
 * P1 全量回归：遍历五个视图，检查渲染、控制台错误、失败请求、无障碍基线。
 * 用法：node scripts/verify-p1-all.cjs（后端需在 :8010）
 */
const { chromium } = require('playwright')

const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:8010/'
const VIEWS = [
  { hash: '#/', name: 'chat', expectTitle: '主对话' },
  { hash: '#/records', name: 'records', expectTitle: '过往记录' },
  { hash: '#/write', name: 'write', expectTitle: '码字编辑' },
  { hash: '#/trace', name: 'trace', expectTitle: '实时流程日志' },
  { hash: '#/retrieval', name: 'retrieval', expectTitle: '检索优化调试' },
]

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  const errors = []
  const failed = []
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
  })
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))
  page.on('response', (r) => {
    if (r.status() >= 400) failed.push(r.status() + ' ' + r.url())
  })

  const results = []

  for (const v of VIEWS) {
    const before = errors.length
    await page.goto(BASE + v.hash, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1800)

    const info = await page.evaluate(() => {
      const view = document.querySelector('.app-view')
      const h2 = document.querySelector('.view-head__title h2')?.textContent?.trim()
      // 检查是否有可见的空白渲染（视图存在但无内容）
      const hasContent = view ? view.children.length > 1 : false
      // 无障碍：模态/面板语义
      const activeNav = document.querySelector('.rail__item.is-active')?.textContent?.trim()
      return {
        h2,
        hasContent,
        activeNav,
        title: document.title,
        // 是否有横向滚动（常见布局问题）
        hasHorizontalScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      }
    })

    results.push({
      view: v.name,
      expectTitle: v.expectTitle,
      ...info,
      newErrors: errors.slice(before),
    })
  }

  // 窄屏检查
  await page.setViewportSize({ width: 900, height: 800 })
  await page.goto(BASE + '#/', { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  const narrow = await page.evaluate(() => ({
    railCollapsed: !!document.querySelector('.rail.is-collapsed'),
    railWidth: Math.round(document.querySelector('.rail')?.getBoundingClientRect().width ?? 0),
    hasHorizontalScroll:
      document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  }))

  const report = {
    views: results,
    allTitlesMatch: results.every((r) => r.h2 === r.expectTitle),
    noNewErrorsPerView: results.every((r) => r.newErrors.length === 0),
    noHorizontalScroll: results.every((r) => !r.hasHorizontalScroll),
    narrow,
    totalErrors: errors,
    failedRequests: failed,
  }

  console.log(JSON.stringify(report, null, 2))
  await browser.close()
})()
