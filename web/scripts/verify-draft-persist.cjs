const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(1400)

  await p.fill('.editor', '视图切换后这段草稿必须还在。')
  await p.waitForTimeout(2600) // 等防抖落盘

  // 切到记录页再切回（触发 unmount → mount，不是整页刷新）
  await p.evaluate(() => { location.hash = '#/records' })
  await p.waitForTimeout(900)
  await p.evaluate(() => { location.hash = '#/write' })
  await p.waitForTimeout(1200)

  const r = await p.evaluate(() => ({
    editorValue: document.querySelector('.editor')?.value ?? '',
    inStorage: !!localStorage.getItem('psy:draft'),
    statusText: document.querySelector('.meta-bar__status')?.textContent?.trim(),
  }))
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
