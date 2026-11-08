const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1680, height: 1000 } })
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(5000)

  // 直接测物理模拟的位移收敛情况
  const diag = await p.evaluate(async () => {
    // 通过重新 import 模块来测（Vite 生产包没有 export，改用观察 canvas 绘制）
    const c = document.querySelector('canvas')
    const ctx = c.getContext('2d')
    const snap = () => {
      const d = ctx.getImageData(0, 0, c.width, c.height).data
      let h = 0
      for (let i = 0; i < d.length; i += 4) h = (h * 31 + d[i]) >>> 0
      return h
    }
    const h1 = snap()
    await new Promise(r => setTimeout(r, 1500))
    const h2 = snap()
    await new Promise(r => setTimeout(r, 1500))
    const h3 = snap()
    return { h1, h2, h3, stillChanging: h1 !== h2 || h2 !== h3 }
  })
  console.log(JSON.stringify(diag, null, 2))
  await b.close()
})()
