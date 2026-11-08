/**
 * P3 验证：图谱引擎（停帧、性能）、富文本渲染、执行链、Inspector。
 */
const { chromium } = require('playwright')

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1680, height: 1000 } })
  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))

  await page.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await page.waitForTimeout(4000)

  const r = {}

  // ---- 1. 图谱画布存在且已绘制 ----
  r.canvas = await page.evaluate(() => {
    const c = document.querySelector('canvas')
    if (!c) return null
    const ctx = c.getContext('2d')
    const rect = c.getBoundingClientRect()
    // 采样检查是否真的画了东西（非全透明）
    const data = ctx.getImageData(0, 0, c.width, c.height).data
    let nonEmpty = 0
    for (let i = 3; i < data.length; i += 4 * 97) if (data[i] > 0) nonEmpty++
    return {
      w: Math.round(rect.width),
      h: Math.round(rect.height),
      pixelW: c.width,
      dpr: window.devicePixelRatio,
      nonEmptySamples: nonEmpty,
      hasAriaLabel: c.getAttribute('aria-label'),
      role: c.getAttribute('role'),
      tabindex: c.getAttribute('tabindex'),
    }
  })

  // ---- 2. 自动停帧：等 3 秒后检查 RAF 是否停止 ----
  r.stopFrame = await page.evaluate(async () => {
    // 注入探针：统计 3 秒内实际发生的 RAF 次数
    let rafCount = 0
    let probing = true
    const probe = () => {
      if (!probing) return
      rafCount++
      requestAnimationFrame(probe)
    }
    requestAnimationFrame(probe)
    await new Promise((res) => setTimeout(res, 3000))
    probing = false
    return { rafCountIn3s: rafCount }
  })

  // ---- 3. 图例与过滤 ----
  r.legend = await page.evaluate(() => ({
    items: [...document.querySelectorAll('.gc__legend-item')].map((x) => x.textContent.trim()),
    filters: [...document.querySelectorAll('.gc__filter')].map((x) => x.textContent.trim()),
    scaleText: document.querySelector('.gc__scale')?.textContent?.trim(),
  }))

  // ---- 4. 无障碍等价列表 ----
  r.a11y = await page.evaluate(() => {
    const details = document.querySelector('.gc__a11y')
    return {
      exists: !!details,
      summary: details?.querySelector('summary')?.textContent?.trim(),
      itemCount: details?.querySelectorAll('.gc__a11y-item').length ?? 0,
    }
  })

  // ---- 5. 点击节点 → Inspector ----
  const box = await page.evaluate(() => {
    const c = document.querySelector('canvas')
    const r = c?.getBoundingClientRect()
    return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null
  })
  if (box) {
    // 会话节点在中心，点中心位置
    await page.mouse.click(box.x + box.w / 2, box.y + box.h / 2)
    await page.waitForTimeout(900)
  }
  r.inspector = await page.evaluate(() => {
    const ins = document.querySelector('.ins')
    if (!ins) return { open: false }
    return {
      open: true,
      type: ins.querySelector('.ins__type')?.textContent?.trim(),
      title: ins.querySelector('.ins__title')?.textContent?.trim(),
      sections: [...ins.querySelectorAll('.ins__section h4')].map((x) => x.textContent.trim()),
      neighbors: ins.querySelectorAll('.ins__neighbor').length,
    }
  })

  // ---- 6. 缩放控件 ----
  const zoomIn = await page.$('.gc__ctl[aria-label="放大"]')
  if (zoomIn) {
    await zoomIn.click()
    await page.waitForTimeout(500)
  }
  r.zoom = await page.evaluate(() => ({
    scaleText: document.querySelector('.gc__scale')?.textContent?.trim(),
  }))

  // ---- 7. 富文本：检查加粗/列表/引用是否渲染为真实元素 ----
  r.richtext = await page.evaluate(() => ({
    bubbles: document.querySelectorAll('.msg__bubble .rt').length,
    strongTags: document.querySelectorAll('.rt .rt__strong').length,
    listTags: document.querySelectorAll('.rt .rt__list').length,
    quoteTags: document.querySelectorAll('.rt .rt__quote').length,
    citeChips: document.querySelectorAll('.cite').length,
    // 关键：不应存在未解析的 markdown 标记
    rawStars: [...document.querySelectorAll('.rt__text')].some((el) => el.textContent.includes('**')),
    rawCiteMarkers: [...document.querySelectorAll('.rt__text')].some((el) => el.textContent.includes('[[cite:')),
  }))

  // ---- 8. 执行链 ----
  r.chain = await page.evaluate(() => {
    const chain = document.querySelector('.chain')
    if (!chain) return { exists: false }
    return {
      exists: true,
      summary: chain.querySelector('.chain__text')?.textContent?.trim(),
      hasTime: !!chain.querySelector('.chain__time'),
      hasBadge: !!chain.querySelector('.chain__badge'),
      collapsedByDefault: !chain.querySelector('.chain__steps'),
    }
  })

  await page.screenshot({ path: '../docs/_shots/p3-chat-graph.png' })
  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await browser.close()
})()
