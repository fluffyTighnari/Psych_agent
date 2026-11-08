/** 记录页结果卡与命中高亮：用真实存在的关键词 */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1600, height: 1000 } })
  const errors = []
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  p.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))

  await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)

  const r = {}
  r.initial = await p.evaluate(() => ({
    cards: document.querySelectorAll('.result-list .disc').length,
    count: document.querySelector('.results-head__count')?.textContent?.trim(),
    firstBadge: document.querySelector('.result-list .rc__badge')?.textContent?.trim(),
    chips: document.querySelectorAll('.result-list .rc__chip').length,
  }))

  // 用真实存在的关键词搜索
  await p.fill('.filter-form input[placeholder*="内耗"]', '掌控感')
  await p.waitForTimeout(200)
  await p.click('.actions button:has-text("搜索")')
  await p.waitForTimeout(2500)

  r.search = await p.evaluate(() => ({
    count: document.querySelector('.results-head__count')?.textContent?.trim(),
    flag: document.querySelector('.results-head__flag')?.textContent?.trim(),
    cards: document.querySelectorAll('.result-list .disc').length,
    highlightMarks: document.querySelectorAll('.result-list .hl__mark').length,
    highlightSample: [...document.querySelectorAll('.result-list .hl__mark')].slice(0, 3).map(x => x.textContent),
  }))

  // 展开第一张卡
  const head = await p.$('.result-list .disc__head')
  if (head) { await head.click(); await p.waitForTimeout(500) }

  r.expanded = await p.evaluate(() => {
    const d = document.querySelector('.result-list .disc')
    return {
      isOpen: d?.classList.contains('is-open'),
      hasDetail: !!d?.querySelector('.rc__detail'),
      hasBody: !!d?.querySelector('.rc__body'),
      actions: [...(d?.querySelectorAll('.rc__action') ?? [])].map(x => x.textContent.trim()),
    }
  })

  // 点击「在对话中追问」应跳转
  const askBtn = await p.$('.result-list .rc__action')
  if (askBtn) {
    await askBtn.click()
    await p.waitForTimeout(1200)
  }
  r.navigatedToChat = await p.evaluate(() => location.hash)

  await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
  await p.waitForTimeout(1500)
  await p.fill('.filter-form input[placeholder*="内耗"]', '掌控感')
  await p.waitForTimeout(200)
  await p.click('.actions button:has-text("搜索")')
  await p.waitForTimeout(2000)
  const h2 = await p.$('.result-list .disc__head')
  if (h2) { await h2.click(); await p.waitForTimeout(600) }
  await p.screenshot({ path: '../docs/_shots/p5-result-card.png' })

  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
