const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
  await p.goto('http://127.0.0.1:8010/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(1500)
  const out = []
  for (let i = 0; i < 8; i++) {
    await p.keyboard.press('Tab')
    await p.waitForTimeout(200)
    out.push(await p.evaluate(() => {
      const a = document.activeElement
      if (!a || a === document.body) return { none: true }
      return {
        tag: a.tagName.toLowerCase(),
        cls: a.className?.toString().slice(0, 40),
        label: a.getAttribute('aria-label'),
        text: (a.textContent || '').trim().slice(0, 14),
        inToast: !!a.closest('.toasts'),
        visible: a.getBoundingClientRect().width > 0,
      }
    }))
  }
  console.log(JSON.stringify(out, null, 2))
  await b.close()
})()
