const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1500, height: 980 } })
  const errors = []
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  p.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  const info = await p.evaluate(() => ({
    appHtmlLen: document.getElementById('app')?.innerHTML.length,
    hasChatView: !!document.querySelector('.chat-view'),
    hasChatMain: !!document.querySelector('.chat-main'),
    topClasses: [...document.querySelectorAll('.chat-view > *')].map(x => x.className),
    modePicker: !!document.querySelector('.mode-picker'),
    composer: !!document.querySelector('.composer'),
    bodyText: document.body.innerText.slice(0, 200),
  }))
  console.log(JSON.stringify({ info, errors }, null, 2))
  await p.screenshot({ path: '../docs/_shots/debug-chat.png' })
  await b.close()
})()
