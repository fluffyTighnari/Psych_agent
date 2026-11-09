const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')
;(async () => {
  const dir = path.resolve('public/brand/graph')
  const toData = (f) =>
    'data:image/svg+xml;base64,' + fs.readFileSync(path.join(dir, f)).toString('base64')
  const files = ['session-orbit.svg', 'concept-knowledge.svg', 'concept-memory.svg', 'concept-guidance.svg']
  const labels = ['session 轨道环', 'document 纸页', 'memory 卡片', 'reason 纸飞机']
  const sizes = [34, 52, 110]

  const b = await chromium.launch()
  const p = await (await b.newContext({ viewport: { width: 900, height: 420 }, deviceScaleFactor: 3 })).newPage()

  let html = '<body style="margin:0;background:#f7f2e8;font:12px system-ui;color:#2a231c">'
  html += '<div style="display:flex;gap:30px;padding:10px 16px;align-items:flex-end;color:#746750">'
  html += '<span style="width:52px"></span>'
  for (const l of labels) html += `<span style="width:110px;text-align:center">${l}</span>`
  html += '</div>'
  for (const s of sizes) {
    html += `<div style="display:flex;gap:30px;padding:14px 16px;align-items:center;border-top:1px solid #e6dcc8">`
    html += `<span style="width:52px;color:#746750">${s}px</span>`
    for (const f of files) {
      html += `<span style="width:110px;display:grid;place-items:center"><img src="${toData(f)}" width="${s}" height="${s}"></span>`
    }
    html += '</div>'
  }
  html += '</body>'

  await p.setContent(html, { waitUntil: 'networkidle' })
  await p.waitForTimeout(500)
  await p.screenshot({ path: '../docs/_shots/glyph-sizes.png', clip: { x: 0, y: 0, width: 620, height: 320 } })
  console.log('ok')
  await b.close()
})()
