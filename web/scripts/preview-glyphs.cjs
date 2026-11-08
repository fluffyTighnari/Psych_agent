/** 把四个字形渲染成一张对比图，人工确认几何 */
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

// 直接从 TS 源里取路径不方便，这里内联一份等价实现用于预览
const S = (r=1)=>({})
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 900, height: 300 }, deviceScaleFactor: 3 })
  await p.setContent(`
    <body style="margin:0;background:#f7f2e8;display:flex;align-items:center;justify-content:center;height:300px;gap:60px">
      <div id="out" style="display:flex;gap:70px;align-items:center"></div>
    </body>
  `)
  await b.close()
})()
