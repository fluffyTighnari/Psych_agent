/** 第三轮反馈验证 */
const { chromium } = require('playwright')
const { AxeBuilder } = require('@axe-core/playwright')

async function withPage(fn) {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  try { return { ...(await fn(p)), errors } } finally { await b.close() }
}

;(async () => {
  const out = {}

  // 1. 哨兵剥离
  out.sentinel = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
    await p.waitForTimeout(3500)
    return await p.evaluate(() => {
      const texts = [...document.querySelectorAll('.msg--assistant .rt')].map(e => e.textContent || '')
      return {
        bubbles: texts.length,
        leaked: texts.filter(t => t.includes('心理咨询回复')).length,
        sample: texts[0]?.slice(0, 40) ?? '',
      }
    })
  })

  // 2. 输入框聚焦边框 + 刻度轨
  out.chat = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
    await p.waitForTimeout(3500)

    await p.click('.composer__input')
    await p.waitForTimeout(300)
    const composer = await p.evaluate(() => {
      const el = document.querySelector('.composer__box')
      const cs = getComputedStyle(el)
      return { border: cs.borderColor, shadow: cs.boxShadow, hasBigShadow: cs.boxShadow !== 'none' }
    })

    const rail = await p.evaluate(() => ({
      ticks: document.querySelectorAll('.rail-ticks .mark').length,
      links: document.querySelectorAll('.rail-ticks__link').length,
      hasPanel: !!document.querySelector('.rail-panel'),
      kinds: [...document.querySelectorAll('.rail-ticks .mark')].map(m =>
        [...m.classList].filter(c => c.startsWith('mark--')).join(',')),
    }))

    return { composer, rail }
  })

  // 3. 追问 → 附件 chip
  out.replyTo = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
    await p.waitForTimeout(3500)
    // hover 消息让操作栏出现
    const msg = await p.$('.msg--assistant')
    if (msg) { await msg.hover(); await p.waitForTimeout(300) }
    const replyBtn = await p.$('.msg--assistant button:has-text("追问")')
    if (replyBtn) { await replyBtn.click(); await p.waitForTimeout(600) }
    return await p.evaluate(() => ({
      chips: document.querySelectorAll('.composer__chip').length,
      chipText: document.querySelector('.composer__chip')?.textContent?.trim().replace(/\s+/g, ' ') ?? null,
    }))
  })

  // 4. 编辑页宽度
  out.write = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
    await p.waitForTimeout(2200)
    const normal = await p.evaluate(() => {
      const w = document.querySelector('.editor-wrap')
      const r = w?.getBoundingClientRect()
      return { width: Math.round(r?.width ?? 0), ratio: Math.round(((r?.width ?? 0) / window.innerWidth) * 100) }
    })
    await p.click('button:has-text("专注")')
    await p.waitForTimeout(700)
    const focus = await p.evaluate(() => {
      const w = document.querySelector('.editor-wrap')
      const r = w?.getBoundingClientRect()
      return { width: Math.round(r?.width ?? 0), ratio: Math.round(((r?.width ?? 0) / window.innerWidth) * 100) }
    })
    return { normal, focus }
  })

  // 5. 无障碍
  out.a11y = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
    await p.waitForTimeout(2500)
    const axe = await new AxeBuilder({ page: p }).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze()
    return { violations: axe.violations.length, ids: axe.violations.map(v => v.id) }
  })

  console.log(JSON.stringify(out, null, 2))
})()
