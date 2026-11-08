/** 排名迁移图：验证空列已移除、标题不裁切、hover 生效 */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1600, height: 1000 } })
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
  await p.waitForTimeout(1000)

  const r = await p.evaluate(() => {
    const c = document.querySelector('.rs__canvas')
    if (!c) return { noCanvas: true }
    const ctx = c.getContext('2d')
    const d = ctx.getImageData(0, 0, c.width, c.height).data
    let drawn = 0
    for (let i = 3; i < d.length; i += 4 * 53) if (d[i] > 0) drawn++
    // 检查画布内容最右侧是否有非空像素（即标题没被裁掉）
    const rightEdge = ctx.getImageData(c.width - 40, 0, 40, c.height).data
    let rightHasContent = false
    for (let i = 3; i < rightEdge.length; i += 4) if (rightEdge[i] > 0) { rightHasContent = true; break }
    return {
      visibleCols: document.querySelectorAll('.rs__table thead th').length,
      tableRows: document.querySelectorAll('.rs__table tbody tr').length,
      drawn,
      rightHasContent,
      canvasW: c.width,
      aria: c.getAttribute('aria-label'),
    }
  })

  // hover 命中检测
  const box = await p.evaluate(() => {
    const c = document.querySelector('.rs__canvas').getBoundingClientRect()
    return { x: c.x, y: c.y, w: c.width, h: c.height }
  })
  let hoverHit = false
  // 扫几个位置找命中点
  for (let fy = 0.15; fy < 0.9 && !hoverHit; fy += 0.08) {
    for (let fx = 0.1; fx < 0.85 && !hoverHit; fx += 0.06) {
      await p.mouse.move(box.x + box.w * fx, box.y + box.h * fy)
      await p.waitForTimeout(60)
      const cur = await p.evaluate(() => document.querySelector('.rs__canvas')?.style.cursor)
      if (cur === 'pointer') hoverHit = true
    }
  }
  r.hoverHit = hoverHit

  const chart = await p.$('.rs')
  if (chart) await chart.screenshot({ path: '../docs/_shots/p5-rankshift-fixed.png' })

  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
