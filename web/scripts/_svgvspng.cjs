const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

/**
 * A/B：同一图形，SVG 直接缩放 vs 预先在目标尺寸栅格化成 PNG。
 * 目标是验证"PNG 会不会比 SVG 更精致"，而不是凭感觉判断。
 */
;(async () => {
  const dir = path.resolve('public/brand/graph')
  const svg = fs.readFileSync(path.join(dir, 'session-orbit.svg'))

  const b = await chromium.launch()
  const p = await (await b.newContext({ viewport: { width: 900, height: 400 }, deviceScaleFactor: 2 })).newPage()

  // 用浏览器把 SVG 栅格化成不同目标尺寸的 PNG（模拟"设计师导出的 PNG"）
  async function rasterize(size) {
    const data = await p.evaluate(
      async ([src, px]) => {
        const blob = new Blob([src], { type: 'image/svg+xml' })
        const url = URL.createObjectURL(blob)
        const img = new Image()
        await new Promise((res, rej) => {
          img.onload = res
          img.onerror = rej
          img.src = url
        })
        const c = document.createElement('canvas')
        c.width = px
        c.height = px
        const ctx = c.getContext('2d')
        ctx.imageSmoothingQuality = 'high'
        ctx.drawImage(img, 0, 0, px, px)
        return c.toDataURL('image/png')
      },
      [svg.toString('utf8'), size],
    )
    return data
  }

  const svgData = 'data:image/svg+xml;base64,' + svg.toString('base64')
  const png34 = await rasterize(68) // 34 CSS px @2x
  const png52 = await rasterize(104)
  const png156 = await rasterize(312)

  let html = '<body style="margin:0;background:#f7f2e8;font:12px system-ui;color:#2a231c">'
  html += '<div style="padding:10px 16px;color:#746750">同一图形：左＝SVG 实时缩放　右＝预栅格化 PNG</div>'
  for (const [label, size, png] of [['34px', 34, png34], ['52px', 52, png52], ['156px (300%)', 156, png156]]) {
    html += `<div style="display:flex;gap:24px;padding:12px 16px;align-items:center;border-top:1px solid #e6dcc8">
      <span style="width:90px;color:#746750">${label}</span>
      <img src="${svgData}" width="${size}" height="${size}">
      <span style="color:#a89a86">vs</span>
      <img src="${png}" width="${size}" height="${size}" style="image-rendering:auto">
    </div>`
  }
  html += '</body>'
  await p.setContent(html, { waitUntil: 'networkidle' })
  await p.waitForTimeout(600)
  await p.screenshot({ path: '../docs/_shots/glyph-svg-vs-png.png', clip: { x: 0, y: 0, width: 460, height: 380 } })

  // 同时报告体积
  const pngBytes = (s) => Math.round((s.length - 'data:image/png;base64,'.length) * 0.75)
  console.log('SVG 体积:', svg.length, 'bytes')
  console.log('PNG@2x(68px) :', pngBytes(png34), 'bytes')
  console.log('PNG@2x(104px):', pngBytes(png52), 'bytes')
  console.log('PNG@2x(312px):', pngBytes(png156), 'bytes')
  await b.close()
})()
