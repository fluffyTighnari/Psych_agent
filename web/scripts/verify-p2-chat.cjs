/**
 * P2 主对话验证：真实发一条消息，检查 TurnTrace 阶段递进、流式渲染、引用、ThreadRail。
 * 需要后端在 :8010 且模型可用（本机 Ollama / API）。
 */
const { chromium } = require('playwright')

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1500, height: 980 } })
  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))

  await page.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await page.waitForTimeout(2000)

  const r = {}

  r.initial = await page.evaluate(() => ({
    hasEmptyState: !!document.querySelector('.chat-empty'),
    modeCards: [...document.querySelectorAll('.mode-card__title')].map((x) => x.textContent.trim()),
    composerPlaceholder: document.querySelector('.composer__input')?.placeholder,
    railTicks: document.querySelectorAll('.rail-ticks__list .mark').length,
  }))

  // 选直接咨询
  await page.click('.mode-card:first-child')
  await page.waitForTimeout(200)

  // 发一条消息
  await page.fill('.composer__input', '我最近总觉得自己不够好，做事之前先想别人会怎么评价我。')
  await page.waitForTimeout(200)

  const t0 = Date.now()
  await page.click('button:has-text("发送")')

  // 采集中间态：TurnTrace 是否在等待期出现
  await page.waitForTimeout(2500)
  r.duringWait = await page.evaluate(() => ({
    hasTurnTrace: !!document.querySelector('.tt'),
    ttRunning: !!document.querySelector('.tt--running'),
    titleText: document.querySelector('.tt__title')?.textContent?.trim().slice(0, 30),
    stageCount: document.querySelectorAll('.tt__step:not(.tt__step--pending)').length,
    hasUserBubble: !!document.querySelector('.msg--user'),
    hasWaitingDots: !!document.querySelector('.msg__waiting'),
    canAbort: [...document.querySelectorAll('button')].some((b) => b.textContent.includes('停止')),
  }))

  // 等回复完成（最多 3 分钟，本地模型可能慢）
  let finished = false
  for (let i = 0; i < 180; i++) {
    await page.waitForTimeout(1000)
    finished = await page.evaluate(() => {
      const tt = document.querySelector('.tt')
      return !!tt && !tt.classList.contains('tt--running')
    })
    if (finished) break
  }

  const elapsed = Date.now() - t0

  r.afterComplete = await page.evaluate(() => {
    const tt = document.querySelector('.tt')
    const bubble = document.querySelector('.msg--assistant .msg__bubble')
    const plain = [...document.querySelectorAll('.msg--assistant .msg__plain')].map((x) => x.textContent).join('')
    return {
      ttTitle: tt?.querySelector('.tt__title')?.textContent?.trim(),
      stages: [...document.querySelectorAll('.tt__step:not(.tt__step--pending)')].map((s) => ({
        name: s.querySelector('.tt__name')?.textContent?.trim(),
        summary: s.querySelector('.tt__summary')?.textContent?.trim(),
        dur: s.querySelector('.tt__dur')?.textContent?.trim(),
      })),
      replyLength: plain.length,
      replyPreview: plain.slice(0, 80),
      citationChips: document.querySelectorAll('.cite').length,
      hasActions: !!document.querySelector('.msg__actions'),
      hasReportCard: !!document.querySelector('.msg__advice'),
    }
  })

  // ThreadRail 刻度
  r.rail = await page.evaluate(() => ({
    ticks: document.querySelectorAll('.rail-ticks__list .mark').length,
    kinds: [...document.querySelectorAll('.rail-ticks__list .mark')].map((m) =>
      [...m.classList].filter((c) => c.startsWith('mark--')).join(','),
    ),
    currentMarked: !!document.querySelector('.rail-ticks__list .mark.is-current'),
  }))

  // 展开大纲
  await page.click('.rail-ticks__toggle')
  await page.waitForTimeout(500)
  r.railExpanded = await page.evaluate(() => ({
    panelVisible: !!document.querySelector('.rail-panel'),
    entries: [...document.querySelectorAll('.rail-panel .entry__label')].map((x) => x.textContent.trim()),
    filters: [...document.querySelectorAll('.rail-panel__filter')].map((x) => x.textContent.trim()),
  }))

  await page.screenshot({ path: '../docs/_shots/p2-chat.png' })

  r.timing = { totalMs: elapsed, finished }
  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await browser.close()
})()
