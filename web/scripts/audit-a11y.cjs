/**
 * 无障碍审计：用 axe-core 扫描五个视图，输出违规详情。
 * 只报告 serious / critical 级别，moderate 与 minor 单独列出供参考。
 */
const { chromium } = require('playwright')
const { AxeBuilder } = require('@axe-core/playwright')

// 新版前端由 main.py 直接挂在根路径（web/dist），不再有 /next/ 前缀。
// 默认值若指向不存在的路径，StaticFiles 会回落到 legacy 页面，扫出来的 0 违规是假的。
const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:8010/'
const VIEWS = [
  { hash: '#/', name: '主对话' },
  { hash: '#/records', name: '过往记录' },
  { hash: '#/write', name: '码字编辑' },
  { hash: '#/trace', name: '流程日志' },
  { hash: '#/retrieval', name: '检索调试' },
]

;(async () => {
  const browser = await chromium.launch()
  // axe-core/playwright 要求显式创建 context
  const context = await browser.newContext({ viewport: { width: 1500, height: 1000 } })
  const page = await context.newPage()

  const all = {}

  for (const v of VIEWS) {
    await page.goto(BASE + v.hash, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2500)

    // 挂载点校验：基础路径写错时会静默落到 legacy 页面，
    // 那样扫出来的「0 违规」是假的（legacy 页面结构完全不同）。
    if (!(await page.$('.app-shell'))) {
      throw new Error(
        `基础路径 ${BASE} 上找不到 .app-shell —— 可能落到了 legacy 兜底页面。` +
          `用 VERIFY_BASE 指定新版前端的实际地址。`,
      )
    }

    const results = await new AxeBuilder({ page })
      // 图谱画布是 Canvas，axe 无法评估其内部，已提供 DOM 等价列表
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()

    all[v.name] = results.violations.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      nodes: violation.nodes.length,
      sample: violation.nodes.slice(0, 2).map((n) => ({
        target: n.target.join(' '),
        summary: (n.failureSummary || '').split('\n').slice(0, 3).join(' | ').slice(0, 180),
      })),
    }))
  }

  const flat = Object.entries(all).flatMap(([view, list]) =>
    list.map((v) => ({ view, ...v })),
  )

  const serious = flat.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  const moderate = flat.filter((v) => v.impact === 'moderate')
  const minor = flat.filter((v) => v.impact === 'minor')

  console.log(
    JSON.stringify(
      {
        summary: {
          total: flat.length,
          seriousOrCritical: serious.length,
          moderate: moderate.length,
          minor: minor.length,
        },
        serious,
        moderate: moderate.map((v) => ({ view: v.view, id: v.id, nodes: v.nodes, help: v.help })),
        minor: minor.map((v) => ({ view: v.view, id: v.id, nodes: v.nodes })),
      },
      null,
      2,
    ),
  )

  await browser.close()
})()
