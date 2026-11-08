/** 批次B 验证：DocumentPeek 四入口、保存语义、容器分级 */
const { chromium } = require('playwright')

;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  const r = {}

  // ---- 1. 记录页 → 阅读全文 ----
  await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2800)

  r.recordCard = await p.evaluate(() => ({
    cardVariant: !!document.querySelector('.disc--v-card'),
    cards: document.querySelectorAll('.disc--v-card').length,
  }))

  // 展开第一张卡，点「阅读全文」
  const head = await p.$('.result-list .disc__head')
  if (head) { await head.click(); await p.waitForTimeout(500) }
  const readBtn = await p.$('.rc__action--primary')
  if (readBtn) { await readBtn.click(); await p.waitForTimeout(1000) }

  r.peek = await p.evaluate(() => {
    const el = document.querySelector('.peek')
    if (!el) return { open: false }
    const cs = getComputedStyle(el)
    return {
      open: true,
      width: Math.round(el.getBoundingClientRect().width),
      role: el.getAttribute('role'),
      title: el.querySelector('.peek__title')?.textContent?.trim().slice(0, 30),
      textFont: el.querySelector('.peek__text') ? getComputedStyle(el.querySelector('.peek__text')).fontSize : null,
      textLen: el.querySelector('.peek__text')?.textContent?.length ?? 0,
      hasSections: el.querySelectorAll('.peek__section').length,
      hasGrip: !!el.querySelector('.peek__grip'),
      actions: [...el.querySelectorAll('.peek__foot button')].map(x => x.textContent.trim()),
    }
  })
  await p.screenshot({ path: '../docs/_shots/batch-b-peek.png' })

  // Esc 关闭
  await p.keyboard.press('Escape')
  await p.waitForTimeout(600)
  r.peekClosed = await p.evaluate(() => !document.querySelector('.peek'))

  // ---- 2. 检索调试：最终结果可点 ----
  await p.goto('http://127.0.0.1:8010/#/retrieval', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  await p.fill('.rd-panel textarea', '最近总是内耗，怎么和自己和解')
  await p.click('.rd-actions button:has-text("运行检索")')
  for (let i = 0; i < 240; i++) {
    await p.waitForTimeout(1000)
    const done = await p.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('运行检索'))
      return btn && !btn.disabled
    })
    if (done) break
  }
  await p.waitForTimeout(800)

  r.finalResultClickable = await p.evaluate(() => {
    const card = document.querySelector('.final-card')
    return {
      exists: !!card,
      hasRole: card?.getAttribute('role'),
      hasTabindex: card?.getAttribute('tabindex'),
      cursor: card ? getComputedStyle(card).cursor : null,
    }
  })

  // 点第一张最终结果卡
  const fc = await p.$('.final-card')
  if (fc) { await fc.click(); await p.waitForTimeout(900) }
  r.retrievalPeek = await p.evaluate(() => ({
    open: !!document.querySelector('.peek'),
    title: document.querySelector('.peek__title')?.textContent?.trim().slice(0, 28),
  }))
  await p.keyboard.press('Escape')
  await p.waitForTimeout(400)

  // 日志容器分级
  r.logVariant = await p.evaluate(() => ({
    logItems: document.querySelectorAll('.logs .disc--v-line').length,
    finalCards: document.querySelectorAll('.final-card').length,
  }))

  // ---- 3. 编辑页保存语义 ----
  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2200)
  await p.click('.cm-content')
  await p.keyboard.type('验证保存语义拆分')
  await p.waitForTimeout(2800)

  r.saveSemantics = await p.evaluate(() => ({
    states: [...document.querySelectorAll('.meta-bar__state')].map(x => x.textContent.trim().replace(/\s+/g, ' ')),
    warnBadge: document.querySelector('.meta-bar__warn')?.textContent?.trim().replace(/\s+/g, ' ') ?? null,
    buttonText: [...document.querySelectorAll('.actions button')].map(x => x.textContent.trim()),
  }))
  await p.screenshot({ path: '../docs/_shots/batch-b-write.png' })

  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
