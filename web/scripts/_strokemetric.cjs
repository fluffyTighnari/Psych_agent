const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')
;(async () => {
  const dir = path.resolve('public/brand/graph')
  const svg = fs.readFileSync(path.join(dir, 'concept-knowledge.svg'))
  const svgData = 'data:image/svg+xml;base64,' + svg.toString('base64')

  const b = await chromium.launch()
  const p = await (await b.newContext({ viewport: { width: 700, height: 300 }, deviceScaleFactor: 2 })).newPage()

  // 按 48 设计坐标 → 实际显示像素换算：displayPx / 48 * strokeWidth
  const rows = [34, 38, 52, 102, 156]
  const strokeVals = [1.4, 1.9]

  let html = '<body style="margin:0;background:#f7f2e8;font:12px system-ui;color:#2a231c">'
  html += '<div style="padding:8px 14px;color:#746750">concept-knowledge.svg 在不同显示尺寸下的实际描边宽度</div>'
  for (const px of rows) {
    const widths = strokeVals.map((sw) => ((sw * px) / 48).toFixed(2))
    html += `<div style="display:flex;gap:16px;padding:10px 14px;align-items:center;border-top:1px solid #e6dcc8">
      <span style="width:70px;color:#746750">${px}px</span>
      <img src="${svgData}" width="${px}" height="${px}">
      <span style="color:#6c5f4e">描边 ${widths.join(' / ')} 物理像素</span>
    </div>`
  }
  html += '</body>'
  await p.setContent(html, { waitUntil: 'networkidle' })
  await p.waitForTimeout(500)
  await p.screenshot({ path: '../docs/_shots/glyph-stroke-widths.png', clip: { x: 0, y: 0, width: 480, height: 300 } })

  console.log('显示尺寸 → 实际描边像素 (sw=1.4 / 1.9):')
  for (const px of rows) {
    console.log(`  ${String(px).padStart(4)}px  →  ${((1.4 * px) / 48).toFixed(2)} / ${((1.9 * px) / 48).toFixed(2)}`)
  }
  await b.close()
})()
