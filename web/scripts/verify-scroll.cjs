const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 900 } })
  const p = await ctx.newPage()
  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2200)

  await p.click('.cm-content')
  for (let i = 0; i < 45; i++) await p.keyboard.type('第' + (i+1) + '行：专注模式滚动验证内容。\n')
  await p.waitForTimeout(600)

  const beforeFocus = await p.evaluate(() => {
    const v = document.querySelector('.app-view')
    return { scrollable: v.scrollHeight > v.clientHeight + 2, top: v.scrollTop }
  })

  await p.click('button:has-text("专注")')
  await p.waitForTimeout(800)

  const focusInfo = await p.evaluate(() => {
    const v = document.querySelector('.app-view')
    return { scrollable: v.scrollHeight > v.clientHeight + 2, top: v.scrollTop, sh: v.scrollHeight, ch: v.clientHeight }
  })

  // 滚轮
  await p.mouse.move(750, 500)
  await p.mouse.wheel(0, 500)
  await p.waitForTimeout(500)
  const afterWheel = await p.evaluate(() => document.querySelector('.app-view').scrollTop)

  // 拖滚动条
  await p.evaluate(() => { const v = document.querySelector('.app-view'); v.scrollTop = 0 })
  await p.keyboard.down('PageDown')
  await p.waitForTimeout(400)
  await p.keyboard.up('PageDown')
  const afterPgDn = await p.evaluate(() => document.querySelector('.app-view').scrollTop)

  await p.screenshot({ path: '../docs/_shots/fix-focus-scroll.png' })
  console.log(JSON.stringify({ beforeFocus, focusInfo, afterWheel, afterPgDn, wheelWorks: afterWheel > 0 }, null, 2))
  await b.close()
})()
