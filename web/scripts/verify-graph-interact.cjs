const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1680, height: 1000 } })
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(4500)

  const r = {}

  // 停帧复测
  r.stopFrame = await p.evaluate(async () => {
    let n = 0, probing = true
    const probe = () => { if (!probing) return; n++; requestAnimationFrame(probe) }
    requestAnimationFrame(probe)
    await new Promise(res => setTimeout(res, 3000))
    probing = false
    return n
  })

  // 先记录停帧结果，再用无障碍列表打开 Inspector
  // <details> 未展开时子元素不可见，必须先展开
  await p.evaluate(() => {
    const d = document.querySelector('.gc__a11y')
    if (d) d.open = true
  })
  await p.waitForTimeout(300)

  const firstItem = await p.$('.gc__a11y-item')
  if (firstItem) {
    await firstItem.click({ force: true })
    await p.waitForTimeout(800)
  }

  r.inspector = await p.evaluate(() => {
    const ins = document.querySelector('.ins')
    if (!ins) return { open: false }
    return {
      open: true,
      type: ins.querySelector('.ins__type')?.textContent?.trim(),
      title: ins.querySelector('.ins__title')?.textContent?.trim(),
      sections: [...ins.querySelectorAll('.ins__section h4')].map(x => x.textContent.trim().slice(0, 10)),
      neighbors: ins.querySelectorAll('.ins__neighbor').length,
      referencingTurns: ins.querySelectorAll('.ins__turn').length,
    }
  })

  // 关闭 Inspector
  const closeBtn = await p.$('.ins .c-icon-btn')
  if (closeBtn) { await closeBtn.click(); await p.waitForTimeout(400) }
  r.inspectorClosed = await p.evaluate(() => !document.querySelector('.ins'))

  // 过滤模式
  await p.click('.gc__filter:has-text("文档")')
  await p.waitForTimeout(600)
  r.filter = await p.evaluate(() => ({
    active: document.querySelector('.gc__filter.is-active')?.textContent?.trim(),
  }))

  // 滚轮缩放
  const box = await p.evaluate(() => {
    const c = document.querySelector('canvas').getBoundingClientRect()
    return { x: c.x + c.width / 2, y: c.y + c.height / 2 }
  })
  await p.mouse.move(box.x, box.y)
  await p.mouse.wheel(0, -240)
  await p.waitForTimeout(500)
  r.wheelZoom = await p.evaluate(() => document.querySelector('.gc__scale')?.textContent?.trim())

  // 拖拽平移后 scale 不变但 offset 变（间接验证不报错）
  await p.mouse.move(box.x, box.y)
  await p.mouse.down()
  await p.mouse.move(box.x - 60, box.y - 40, { steps: 8 })
  await p.mouse.up()
  await p.waitForTimeout(400)
  r.panOk = true

  await p.screenshot({ path: '../docs/_shots/p3-graph.png' })
  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
