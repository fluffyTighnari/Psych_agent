const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 3 })
  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  await p.click('.cm-content')
  await p.keyboard.type('聚焦测试')
  await p.waitForTimeout(500)

  // 放大截左侧边缘
  const box = await p.evaluate(() => {
    const el = document.querySelector('.md-editor')
    const r = el.getBoundingClientRect()
    return { x: r.x, y: r.y, w: r.width, h: r.height }
  })
  await p.screenshot({
    path: '../docs/_shots/diag-focus-left.png',
    clip: { x: box.x - 6, y: box.y - 6, width: 140, height: 180 },
  })

  const info = await p.evaluate(() => {
    const ed = document.querySelector('.md-editor')
    const cs = getComputedStyle(ed)
    const gutters = document.querySelector('.cm-gutters')
    const gcs = gutters ? getComputedStyle(gutters) : null
    const scroller = document.querySelector('.cm-scroller')
    const scs = scroller ? getComputedStyle(scroller) : null
    return {
      editorBorderLeft: cs.borderLeft,
      editorBoxShadow: cs.boxShadow,
      gutterBorderRight: gcs?.borderRight,
      gutterBorderLeft: gcs?.borderLeft,
      gutterBg: gcs?.backgroundColor,
      scrollerBorder: scs?.border,
      // 找出所有可能画线的元素
      children: [...document.querySelectorAll('.md-editor *')].slice(0, 12).map(el => {
        const s = getComputedStyle(el)
        const hasBorder = s.borderLeftWidth !== '0px' || s.borderRightWidth !== '0px'
        return hasBorder ? { cls: el.className?.toString().slice(0, 30), bl: s.borderLeft, br: s.borderRight } : null
      }).filter(Boolean),
    }
  })
  console.log(JSON.stringify(info, null, 2))
  await b.close()
})()
