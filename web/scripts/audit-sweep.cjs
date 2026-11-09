const { chromium } = require('playwright')
const VIEWS = [
  ['#/', '主对话'],
  ['#/records', '过往记录'],
  ['#/write', '码字编辑'],
  ['#/trace', '流程日志'],
  ['#/retrieval', '检索调试'],
]
;(async () => {
  const b = await chromium.launch()
  const p = await (await b.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 })).newPage()
  const errs = []
  p.on('pageerror', (e) => errs.push(String(e)))
  p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })

  for (const [hash, name] of VIEWS) {
    await p.goto('http://127.0.0.1:8010/' + hash, { waitUntil: 'networkidle' })
    await p.waitForTimeout(2500)
    const r = await p.evaluate(() => {
      // 检查是否有任何元素 < 13px 且承载中文
      const bad = []
      for (const el of document.querySelectorAll('body *')) {
        const s = getComputedStyle(el)
        const size = parseFloat(s.fontSize)
        if (!Number.isFinite(size) || size >= 13) continue
        const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join('')
        if (!own || !/[一-龥]/.test(own)) continue
        const rect = el.getBoundingClientRect()
        if (rect.width < 2) continue
        bad.push({ cls: (el.getAttribute('class') || el.tagName).slice(0, 36), size, text: own.slice(0, 18) })
      }
      return bad
    })
    console.log(
      `${name.padEnd(5)} <13px中文元素: ${r.length}`,
      r.length ? JSON.stringify(r.slice(0, 4)) : '',
    )
  }
  console.log('控制台错误:', errs.length ? errs.slice(0, 3) : '0')
  await b.close()
})()
