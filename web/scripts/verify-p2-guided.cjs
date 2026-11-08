/** 引导模式验证：模式锁定、进度、显式结束、建议报告卡 */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1500, height: 1000 } })
  const errors = []
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  p.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))

  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2000)
  const r = {}

  // 选引导咨询
  await p.click('.mode-card:nth-child(2)')
  await p.waitForTimeout(200)
  r.modeSelected = await p.evaluate(() => ({
    guidedPressed: document.querySelectorAll('.mode-card')[1]?.getAttribute('aria-pressed'),
  }))

  // 发首条
  await p.fill('.composer__input', '我总是很在意同事对我的看法，开会时不敢表达不同意见。')
  await p.click('button:has-text("发送")')

  // 等首轮完成
  for (let i = 0; i < 180; i++) {
    await p.waitForTimeout(1000)
    const done = await p.evaluate(() => {
      const tt = document.querySelector('.tt')
      return !!tt && !tt.classList.contains('tt--running')
    })
    if (done) break
  }

  r.afterFirst = await p.evaluate(() => ({
    modeLockedBar: !!document.querySelector('.mode-locked'),
    badge: document.querySelector('.mode-locked__badge')?.textContent?.trim(),
    anchor: document.querySelector('.mode-locked__anchor')?.textContent?.trim().slice(0, 25),
    progress: document.querySelector('.mode-locked__progress')?.textContent?.trim(),
    hasEndButton: [...document.querySelectorAll('button')].some(x => x.textContent.includes('结束并生成建议')),
    speakerGuide: !!document.querySelector('.msg--guide'),
    guideChips: document.querySelectorAll('.cite--reason').length,
    playerPlaceholder: document.querySelector('.composer__input')?.placeholder,
  }))

  // 点「结束并生成建议」
  const endBtn = await p.$('button:has-text("结束并生成建议")')
  if (endBtn) {
    await endBtn.click()
    for (let i = 0; i < 180; i++) {
      await p.waitForTimeout(1000)
      const done = await p.evaluate(() => {
        const tts = [...document.querySelectorAll('.tt')]
        return tts.length >= 2 && !tts[tts.length - 1].classList.contains('tt--running')
      })
      if (done) break
    }
  }

  r.afterEnd = await p.evaluate(() => ({
    adviceCards: document.querySelectorAll('.msg__advice').length,
    adviceTitle: document.querySelector('.msg__advice-title')?.textContent?.trim(),
    hasAdviceText: (document.querySelector('.msg__advice')?.textContent?.length ?? 0) > 100,
    turnCount: document.querySelectorAll('.chat-turn').length,
    railTicks: document.querySelectorAll('.rail-ticks__list .mark').length,
    reportMark: [...document.querySelectorAll('.rail-ticks__list .mark')].some(m => m.classList.contains('mark--report')),
  }))

  await p.screenshot({ path: '../docs/_shots/p2-guided.png' })
  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
