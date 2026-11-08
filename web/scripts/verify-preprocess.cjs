/** 预处理链路：点按钮 → 完成 → 文档数变化 */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1500, height: 1000 } })
  const errors = []
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  p.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))

  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2000)

  const before = await p.evaluate(async () => {
    const r = await fetch('/knowledge/all')
    const j = await r.json()
    return j.data?.length ?? 0
  })

  // 点预处理
  await p.click('.actions button:has-text("预处理")')

  // 等完成（可能较慢）
  let done = false
  for (let i = 0; i < 240; i++) {
    await p.waitForTimeout(1000)
    done = await p.evaluate(() => {
      const btn = [...document.querySelectorAll('.actions button')].find(b => b.textContent.includes('预处理'))
      return btn && !btn.disabled
    })
    if (done) break
  }

  const after = await p.evaluate(async () => {
    const r = await fetch('/knowledge/all')
    const j = await r.json()
    return j.data?.length ?? 0
  })

  const toast = await p.evaluate(() => document.querySelector('.toast')?.textContent?.trim().slice(0, 60) ?? null)

  console.log(JSON.stringify({ docsBefore: before, docsAfter: after, finished: done, toast, errors }, null, 2))
  await b.close()
})()
