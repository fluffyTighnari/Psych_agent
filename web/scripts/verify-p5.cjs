/**
 * P5 验证：检索调试全流程 + 排名迁移图 + 记录页结果卡。
 */
const { chromium } = require('playwright')

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))

  const r = {}

  /* ============ 检索调试 ============ */
  await page.goto('http://127.0.0.1:8010/#/retrieval', { waitUntil: 'networkidle' })
  await page.waitForTimeout(3000)

  r.initial = await page.evaluate(() => ({
    switches: [...document.querySelectorAll('.switch__name')].map((x) => x.textContent.trim().split(/\s/)[0]),
    switchesOn: document.querySelectorAll('.switch.is-on').length,
    params: [...document.querySelectorAll('.params .field__label')].map((x) => x.textContent.trim()),
    runDisabled: [...document.querySelectorAll('button')].find((b) => b.textContent.includes('运行检索'))?.disabled,
    docCount: document.querySelectorAll('.doc-list .disc').length,
    docHint: document.querySelector('.rd-panel__hint')?.textContent?.trim().slice(0, 40),
  }))

  // 填 prompt 并运行
  await page.fill('.rd-panel textarea', '最近总是内耗，怎么和自己和解')
  await page.waitForTimeout(300)
  r.canRunNow = await page.evaluate(() =>
    ![...document.querySelectorAll('button')].find((b) => b.textContent.includes('运行检索'))?.disabled,
  )

  const t0 = Date.now()
  await page.click('.rd-actions button:has-text("运行检索")')

  // 等运行完成（最多 4 分钟）
  let done = false
  for (let i = 0; i < 240; i++) {
    await page.waitForTimeout(1000)
    done = await page.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('运行检索'))
      return btn && !btn.disabled && !btn.querySelector('.spin')
    })
    if (done) break
  }
  const elapsed = Date.now() - t0

  r.afterRun = await page.evaluate(() => {
    const canvas = document.querySelector('.rs__canvas')
    let drawn = 0
    if (canvas) {
      const ctx = canvas.getContext('2d')
      const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data
      for (let i = 3; i < d.length; i += 4 * 53) if (d[i] > 0) drawn++
    }
    return {
      stats: [...document.querySelectorAll('.stat')].map((s) => s.textContent.trim().replace(/\s+/g, ' ')),
      finalCards: document.querySelectorAll('.final-card').length,
      stagePanels: document.querySelectorAll('.stages .disc').length,
      logItems: document.querySelectorAll('.logs .disc').length,
      chartCanvas: !!canvas,
      chartDrawnSamples: drawn,
      chartAria: canvas?.getAttribute('aria-label')?.slice(0, 60) ?? null,
      chartLegend: [...document.querySelectorAll('.rs__legend-item')].map((x) => x.textContent.trim()),
      tableRows: document.querySelectorAll('.rs__table tbody tr').length,
      queryRewrite: document.querySelector('.kv dd')?.textContent?.trim().slice(0, 40) ?? null,
      errorShown: !!document.querySelector('.rd-error'),
    }
  })

  // 排名迁移图特写
  const chart = await page.$('.rs')
  if (chart) await chart.screenshot({ path: '../docs/_shots/p5-rankshift.png' })

  // hover 图表检查高亮
  const cbox = await page.evaluate(() => {
    const c = document.querySelector('.rs__canvas')
    const r = c?.getBoundingClientRect()
    return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null
  })
  if (cbox) {
    await page.mouse.move(cbox.x + cbox.w * 0.3, cbox.y + 60)
    await page.waitForTimeout(400)
    r.chartHover = await page.evaluate(() => {
      const c = document.querySelector('.rs__canvas')
      return { cursor: c?.style.cursor || '(default)' }
    })
  }

  await page.screenshot({ path: '../docs/_shots/p5-retrieval.png' })

  /* ============ 记录页 ============ */
  await page.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)

  r.records = await page.evaluate(() => ({
    resultCards: document.querySelectorAll('.result-list .disc').length,
    firstLabel: document.querySelector('.result-list .disc__label')?.textContent?.trim(),
    badges: [...document.querySelectorAll('.result-list .rc__badge')].slice(0, 4).map((x) => x.textContent.trim()),
    chips: document.querySelectorAll('.result-list .rc__chip').length,
    count: document.querySelector('.results-head__count')?.textContent?.trim(),
  }))

  // 搜索以触发高亮
  await page.fill('.filter-form input[placeholder*="内耗"]', '内耗, 焦虑')
  await page.click('.actions button:has-text("搜索")')
  await page.waitForTimeout(2500)

  r.search = await page.evaluate(() => ({
    count: document.querySelector('.results-head__count')?.textContent?.trim(),
    flag: document.querySelector('.results-head__flag')?.textContent?.trim(),
    highlights: document.querySelectorAll('.result-list .hl__mark').length,
    cards: document.querySelectorAll('.result-list .disc').length,
  }))

  // 展开一张卡
  const firstHead = await page.$('.result-list .disc__head')
  if (firstHead) { await firstHead.click(); await page.waitForTimeout(500) }
  r.expanded = await page.evaluate(() => {
    const d = document.querySelector('.result-list .disc')
    return {
      isOpen: d?.classList.contains('is-open'),
      hasDetail: !!d?.querySelector('.rc__detail'),
      actions: [...(d?.querySelectorAll('.rc__action') ?? [])].map((x) => x.textContent.trim()),
      hasBody: !!d?.querySelector('.rc__body'),
    }
  })

  await page.screenshot({ path: '../docs/_shots/p5-records.png' })

  r.timing = { runMs: elapsed, runFinished: done }
  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await browser.close()
})()
