const { chromium } = require('playwright')

/** 在真实页面上量出所有「小字 + mono/serif 字体」的元素，按字号排序 */
const VIEWS = [
  ['#/', '主对话'],
  ['#/records', '过往记录'],
  ['#/write', '码字编辑'],
  ['#/trace', '流程日志'],
  ['#/retrieval', '检索调试'],
]

;(async () => {
  const b = await chromium.launch()
  const p = await (await b.newContext({ viewport: { width: 1500, height: 950 } })).newPage()
  const out = []
  for (const [hash, name] of VIEWS) {
    await p.goto('http://127.0.0.1:8010/' + hash, { waitUntil: 'networkidle' })
    await p.waitForTimeout(2400)
    const rows = await p.evaluate((view) => {
      const res = []
      for (const el of document.querySelectorAll('body *')) {
        const s = getComputedStyle(el)
        const size = parseFloat(s.fontSize)
        if (!Number.isFinite(size) || size >= 13.5) continue
        // 只统计有可见文字的元素
        const own = [...el.childNodes]
          .filter((n) => n.nodeType === 3)
          .map((n) => n.textContent.trim())
          .join('')
        if (!own) continue
        const r = el.getBoundingClientRect()
        if (r.width < 2 || r.height < 2) continue
        const fam = s.fontFamily.toLowerCase()
        // 注意顺序：'sans-serif' 里也含 'serif'，必须先判 sans-serif
        const kind = fam.includes('mono')
          ? 'mono'
          : fam.includes('sans-serif')
            ? 'sans'
            : fam.includes('serif')
              ? 'serif'
              : 'sans'
        res.push({
          view,
          cls: (el.getAttribute('class') || el.tagName).slice(0, 40),
          size: Math.round(size * 10) / 10,
          weight: s.fontWeight,
          family: kind,
          text: own.replace(/\s+/g, ' ').slice(0, 26),
        })
      }
      return res
    }, name)
    out.push(...rows)
  }
  // 归并：同 class + size + family 的只留一条，附出现次数
  const map = new Map()
  for (const r of out) {
    const k = `${r.view}|${r.cls}|${r.size}|${r.family}`
    if (!map.has(k)) map.set(k, { ...r, n: 1 })
    else map.get(k).n++
  }
  const list = [...map.values()].sort((a, b) => a.size - b.size || b.n - a.n)
  for (const r of list) {
    console.log(
      `${String(r.size).padStart(5)}px ${r.family.padEnd(5)} w${r.weight} ×${String(r.n).padStart(2)}  ${r.view.padEnd(5)} ${r.cls.padEnd(34)} ${r.text}`,
    )
  }
  console.log('\ntotal distinct:', list.length)
  await b.close()
})()
