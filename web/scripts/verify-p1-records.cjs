const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1440, height: 980 } })
  const errors = []
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  p.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))

  await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)

  const r = {}

  r.initial = await p.evaluate(() => ({
    countText: document.querySelector('.results-head__count')?.textContent?.trim(),
    fields: document.querySelectorAll('.field').length,
    topicPills: document.querySelectorAll('.topics__grid .pill').length,
    modePills: document.querySelectorAll('.submodes .pill').length,
    tabPills: document.querySelectorAll('.tabs .pill').length,
    // 空态或列表
    hasSkeleton: !!document.querySelector('.skeleton'),
    emptyTitle: document.querySelector('.empty__title')?.textContent?.trim() ?? null,
    placeholder: document.querySelector('.placeholder-list')?.textContent?.trim() ?? null,
  }))

  // 选一个主题 → 已选 chips 出现 + 清空按钮启用
  await p.click('.topics__grid .pill:first-child')
  await p.waitForTimeout(300)
  r.afterTopicSelect = await p.evaluate(() => ({
    activeChips: [...document.querySelectorAll('.active-filters__chip')].map(c => c.textContent.trim().replace(/\s+/g,' ')),
    pillPressed: document.querySelector('.topics__grid .pill')?.getAttribute('aria-pressed'),
    clearDisabled: [...document.querySelectorAll('.actions button')].find(b => b.textContent.includes('清空'))?.disabled,
  }))

  // 执行搜索
  await p.click('.actions button:has-text("搜索")')
  await p.waitForTimeout(3000)
  r.afterSearch = await p.evaluate(() => ({
    countText: document.querySelector('.results-head__count')?.textContent?.trim(),
    flag: document.querySelector('.results-head__flag')?.textContent?.trim() ?? null,
    emptyTitle: document.querySelector('.empty__title')?.textContent?.trim() ?? null,
    placeholder: document.querySelector('.placeholder-list')?.textContent?.trim() ?? null,
  }))

  // 精准文本模式：不填原文就点搜索 → 应弹错误 toast
  await p.click('.submodes .pill:nth-child(2)')
  await p.waitForTimeout(400)
  const targetVisible = await p.evaluate(() =>
    [...document.querySelectorAll('.field__label')].some(l => l.textContent.includes('精准文本')))
  await p.click('.actions button:has-text("搜索")')
  await p.waitForTimeout(600)
  r.textModeGuard = {
    targetFieldVisible: targetVisible,
    toastShown: await p.evaluate(() => !!document.querySelector('.toast--err')),
    toastText: await p.evaluate(() => document.querySelector('.toast')?.textContent?.trim().slice(0, 30) ?? null),
  }

  // 切到记忆 tab
  await p.click('.tabs .pill:nth-child(2)')
  await p.waitForTimeout(800)
  r.memoryTab = await p.evaluate(() => ({
    modePills: [...document.querySelectorAll('.submodes .pill')].map(x => x.textContent.trim()),
    countText: document.querySelector('.results-head__count')?.textContent?.trim(),
  }))

  await p.screenshot({ path: '../docs/_shots/p1-records.png' })
  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
