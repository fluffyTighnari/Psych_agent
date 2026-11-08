/** 端到端：保存 → 落盘 → 预处理 → 可检索 */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1500, height: 1000 } })
  const errors = []
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  p.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))

  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)

  // 用唯一的标题避免覆盖已有文档
  const uniqueTitle = 'E2E-验证-' + Date.now().toString(36)
  const r = { uniqueTitle }

  // 切到 Weekly，填三段
  await p.click('.modes .pill:nth-child(2)')
  await p.waitForTimeout(600)

  await p.fill('input[placeholder*="如何停止"]', uniqueTitle)
  await p.fill('input[placeholder*="本周复盘"]', uniqueTitle)

  const editors = await p.$$('.cm-content')
  if (editors[0]) { await editors[0].click(); await p.keyboard.type('这是端到端验证写入的 problem 段落。') }
  if (editors[1]) { await editors[1].click(); await p.keyboard.type('这是 analysis 段落，用于验证保存链路。') }
  if (editors[2]) { await editors[2].click(); await p.keyboard.type('这是 solution 段落，验证完成后应可被检索。') }
  await p.waitForTimeout(800)

  r.beforeSave = await p.evaluate(() => ({
    fill: document.querySelector('.meta-bar__fill')?.textContent?.trim(),
    saveEnabled: ![...document.querySelectorAll('.actions button')].find(b => b.textContent.includes('保存'))?.disabled,
  }))

  // 保存
  await p.click('.actions button:has-text("保存")')
  await p.waitForTimeout(3000)

  r.afterSave = await p.evaluate(() => ({
    toast: document.querySelector('.toast')?.textContent?.trim().slice(0, 60) ?? null,
    status: document.querySelector('.meta-bar__status')?.textContent?.trim(),
    hasPreprocessAction: [...document.querySelectorAll('.toast__action')].some(a => a.textContent.includes('预处理')),
  }))

  await p.screenshot({ path: '../docs/_shots/p4-saved.png' })
  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
