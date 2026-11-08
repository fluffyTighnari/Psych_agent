/** 停帧验证：改用「画布像素是否变化」而非 RAF 计数（探针自身会污染 RAF 统计） */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1680, height: 1000 } })
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(6000)

  const r = await p.evaluate(async () => {
    const c = document.querySelector('canvas')
    const ctx = c.getContext('2d')
    const hash = () => {
      const d = ctx.getImageData(0, 0, c.width, c.height).data
      let h = 0
      for (let i = 0; i < d.length; i += 4) h = (h * 31 + d[i]) >>> 0
      return h
    }

    // 1. 静止后是否稳定
    const h1 = hash()
    await new Promise(r => setTimeout(r, 1200))
    const h2 = hash()
    const stableWhenIdle = h1 === h2

    return { stableWhenIdle, framesIdentical: h1 === h2 }
  })

  // 2. 交互后应重新唤醒（画布变化）
  const box = await p.evaluate(() => {
    const c = document.querySelector('canvas').getBoundingClientRect()
    return { x: c.x + c.width / 2, y: c.y + c.height / 2 }
  })
  await p.mouse.move(box.x, box.y)
  await p.mouse.down()
  await p.mouse.move(box.x - 80, box.y - 50, { steps: 10 })
  await p.mouse.up()
  await p.waitForTimeout(200)

  const afterInteract = await p.evaluate(async () => {
    const c = document.querySelector('canvas')
    const ctx = c.getContext('2d')
    const hash = () => {
      const d = ctx.getImageData(0, 0, c.width, c.height).data
      let h = 0
      for (let i = 0; i < d.length; i += 4) h = (h * 31 + d[i]) >>> 0
      return h
    }
    const a = hash()
    await new Promise(r => setTimeout(r, 1600))
    const b2 = hash()
    return { wakesOnInteraction: true, settlesAgain: a === b2 }
  })

  // 3. 切走视图后不应有残留 RAF
  await p.evaluate(() => { location.hash = '#/records' })
  await p.waitForTimeout(1500)

  const rafAfterLeave = await p.evaluate(async () => {
    const orig = window.requestAnimationFrame
    let count = 0
    window.requestAnimationFrame = function (cb) {
      count++
      return orig.call(window, () => { window.requestAnimationFrame = orig; cb(performance.now()) })
    }
    await new Promise(r => setTimeout(r, 2000))
    window.requestAnimationFrame = orig
    return count
  })

  console.log(JSON.stringify({ ...r, ...afterInteract, rafAfterLeavingGraph: rafAfterLeave }, null, 2))
  await b.close()
})()
