const { chromium } = require('playwright')

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))

  await page.goto('http://127.0.0.1:8010/#/trace', { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)

  const report = {}

  // 1. 列表是否渲染
  report.list = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.disc')]
    return {
      count: items.length,
      firstLabel: items[0]?.querySelector('.disc__label')?.textContent?.trim(),
      firstStage: items[0]?.querySelector('.stage')?.textContent?.trim(),
      firstMeta: items[0]?.querySelector('.disc__meta')?.textContent?.trim(),
    }
  })

  // 2. AppDisclosure 的可访问性与交互
  report.disclosure = await page.evaluate(() => {
    const head = document.querySelector('.disc__head')
    if (!head) return null
    return {
      tag: head.tagName.toLowerCase(),
      ariaExpanded: head.getAttribute('aria-expanded'),
      hasAriaControls: !!head.getAttribute('aria-controls'),
      caretPresent: !!head.querySelector('.disc__caret'),
    }
  })

  // 点击展开第一个有详情的条目
  const expandable = await page.$('.disc__head')
  if (expandable) {
    await expandable.click()
    await page.waitForTimeout(350)
  }
  report.expanded = await page.evaluate(() => {
    const first = document.querySelector('.disc')
    const body = first?.querySelector('.disc__body')
    return {
      isOpen: first?.classList.contains('is-open') ?? false,
      ariaExpanded: first?.querySelector('.disc__head')?.getAttribute('aria-expanded'),
      bodyVisible: body ? getComputedStyle(body).display !== 'none' : false,
      kvRows: first?.querySelectorAll('.kv dt').length ?? 0,
      caretRotated: first?.querySelector('.disc__caret')
        ? getComputedStyle(first.querySelector('.disc__caret')).transform !== 'none'
        : false,
    }
  })

  // 3. 键盘可达：Tab 到 disclosure 头部并按 Enter 切换
  await page.evaluate(() => document.querySelector('.disc__head')?.focus())
  await page.keyboard.press('Enter')
  await page.waitForTimeout(300)
  report.keyboardToggle = await page.evaluate(() => {
    const first = document.querySelector('.disc')
    return { isOpen: first?.classList.contains('is-open') ?? false }
  })

  // 4. SSE 状态
  report.sse = await page.evaluate(() => {
    const el = document.querySelector('.status')
    return {
      text: el?.textContent?.trim(),
      cls: el?.className,
      ariaLive: el?.getAttribute('aria-live'),
    }
  })

  // 5. 新 trace 到达时实时追加
  const beforeCount = await page.evaluate(() => document.querySelectorAll('.disc').length)
  await page.evaluate(async () => {
    await fetch('/tool/search/meta-filter', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_type: 'weekly' }),
    })
  })
  await page.waitForTimeout(2500)
  const afterCount = await page.evaluate(() => document.querySelectorAll('.disc').length)
  report.realtime = { beforeCount, afterCount, grew: afterCount > beforeCount }

  await page.screenshot({ path: '../docs/_shots/p1-trace.png' })

  report.errors = errors
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
})()
