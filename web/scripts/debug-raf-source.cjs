const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1680, height: 1000 } })

  // 在页面加载前就拦截 RAF，记录调用栈来源
  await p.addInitScript(() => {
    const orig = window.requestAnimationFrame
    window.__rafStacks = {}
    window.requestAnimationFrame = function (cb) {
      const stack = new Error().stack || ''
      // 只截取关键帧
      const key = stack.split('\n').slice(2, 4).join(' | ').slice(0, 120)
      window.__rafStacks[key] = (window.__rafStacks[key] || 0) + 1
      return orig.call(window, cb)
    }
  })

  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(6000)

  const before = await p.evaluate(() => ({ ...window.__rafStacks }))
  await p.waitForTimeout(3000)
  const after = await p.evaluate(() => ({ ...window.__rafStacks }))

  // 计算 3 秒内的增量
  const delta = {}
  for (const k of Object.keys(after)) {
    const d = after[k] - (before[k] || 0)
    if (d > 0) delta[k] = d
  }
  console.log(JSON.stringify({ activeRafSources: delta }, null, 2))
  await b.close()
})()
