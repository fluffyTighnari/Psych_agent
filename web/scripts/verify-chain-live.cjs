/** 新对话的执行链：验证阶段、耗时、引用数全部真实呈现 */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1680, height: 1000 }, deviceScaleFactor: 2 })
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)

  const r = {}
  await p.fill('.composer__input', '我最近在准备一个重要的汇报，越临近越焦虑，晚上睡不好。')
  await p.click('button:has-text("发送")')

  // 等待期：执行链应显示进行中
  await p.waitForTimeout(3000)
  r.duringRun = await p.evaluate(() => {
    const c = document.querySelector('.chain')
    return c ? {
      running: c.classList.contains('chain--running'),
      summary: c.querySelector('.chain__text')?.textContent?.trim(),
      hasCaret: !!c.querySelector('.chain__caret'),
    } : null
  })

  // 等完成
  for (let i = 0; i < 240; i++) {
    await p.waitForTimeout(1000)
    const done = await p.evaluate(() => {
      const cs = [...document.querySelectorAll('.chain')]
      return cs.length > 0 && !cs[cs.length - 1].classList.contains('chain--running')
    })
    if (done) break
  }

  r.afterDone = await p.evaluate(() => {
    const cs = [...document.querySelectorAll('.chain')]
    const c = cs[cs.length - 1]
    return {
      summary: c.querySelector('.chain__text')?.textContent?.trim(),
      time: c.querySelector('.chain__time')?.textContent?.trim() ?? null,
      badge: c.querySelector('.chain__badge')?.textContent?.trim() ?? null,
      hasCaret: !!c.querySelector('.chain__caret'),
    }
  })

  // 展开看阶段
  const all = await p.$$('.chain__summary')
  if (all.length) { await all[all.length - 1].click(); await p.waitForTimeout(600) }

  r.stages = await p.evaluate(() => {
    const cs = [...document.querySelectorAll('.chain')]
    const c = cs[cs.length - 1]
    return [...c.querySelectorAll('.chain__step')].map(s => ({
      name: s.querySelector('.chain__name')?.textContent?.trim(),
      detail: s.querySelector('.chain__detail')?.textContent?.trim() ?? null,
      dur: s.querySelector('.chain__dur')?.textContent?.trim() ?? null,
    }))
  })

  // 执行链截图
  const chains = await p.$$('.chain')
  if (chains.length) await chains[chains.length - 1].screenshot({ path: '../docs/_shots/p3-chain-live.png' })

  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
