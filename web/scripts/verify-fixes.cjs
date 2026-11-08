/** 分阶段独立验证，避免测试脚本自身相互干扰 */
const { chromium } = require('playwright')

async function withPage(fn) {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  try {
    const r = await fn(p)
    return { ...r, errors }
  } finally {
    await b.close()
  }
}

;(async () => {
  const out = {}

  // ===== 1. 编辑页红线 =====
  out.editor = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
    await p.waitForTimeout(2200)
    await p.click('.cm-content')
    await p.keyboard.type('检查')
    await p.waitForTimeout(400)
    const info = await p.evaluate(() => {
      const cs = getComputedStyle(document.querySelector('.md-editor'))
      return {
        borderLeft: cs.borderLeft,
        boxShadow: cs.boxShadow,
        hasAccent: cs.borderLeft.includes('194, 74, 46'),
        bg: cs.backgroundColor,
      }
    })
    const box = await p.evaluate(() => {
      const r = document.querySelector('.md-editor').getBoundingClientRect()
      return { x: r.x, y: r.y }
    })
    await p.screenshot({ path: '../docs/_shots/fix-editor.png', clip: { x: box.x - 4, y: box.y - 4, width: 130, height: 150 } })
    return info
  })

  // ===== 2. 自动聚焦栏目 + 插入选中 =====
  out.pick = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
    await p.waitForTimeout(2200)
    await p.click('.modes .pill:nth-child(2)')
    await p.waitForTimeout(600)

    const pickBtns = await p.$$('.weekly-sec__pick')
    const btnCount = pickBtns.length
    if (pickBtns[1]) { await pickBtns[1].click(); await p.waitForTimeout(1000) }

    const autoTarget = await p.evaluate(() =>
      document.querySelector('.pick__target-btn.is-active')?.textContent?.trim())

    const expandBtn = await p.$('.pick__item button:has-text("展开全文")')
    if (expandBtn) { await expandBtn.click(); await p.waitForTimeout(600) }

    // 选中 20 字并触发 mouseup 捕获
    const selected = await p.evaluate(() => {
      const el = document.querySelector('.pick__full-text')
      if (!el || !el.firstChild) return null
      const range = document.createRange()
      range.setStart(el.firstChild, 25)
      range.setEnd(el.firstChild, 45)
      const sel = window.getSelection()
      sel.removeAllRanges()
      sel.addRange(range)
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
      return sel.toString()
    })
    await p.waitForTimeout(400)

    const hint = await p.evaluate(() => ({
      text: document.querySelector('.pick__full-hint')?.textContent?.trim().replace(/\s+/g, ' '),
      active: document.querySelector('.pick__full-hint')?.classList.contains('is-active'),
      btn: document.querySelector('.pick__item-actions button:last-child')?.textContent?.trim().replace(/\s+/g, ' '),
    }))

    const insertBtn = await p.$('.pick__item-actions button:last-child')
    if (insertBtn) { await insertBtn.click(); await p.waitForTimeout(700) }
    const toast = await p.evaluate(() => document.querySelector('.toast')?.textContent?.trim().slice(0, 40))

    await p.keyboard.press('Escape')
    await p.waitForTimeout(600)
    const written = await p.evaluate(() =>
      [...document.querySelectorAll('.cm-content')].map((e, i) => ({
        i, len: (e.textContent || '').length, head: (e.textContent || '').slice(0, 50),
      })))

    return { btnCount, autoTarget, selected, hint, toast, written }
  })

  // ===== 3. Peek 宽度与点击关闭（独立页面，无干扰） =====
  out.peek = await withPage(async (p) => {
    await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
    await p.waitForTimeout(2500)

    const head = await p.$('.result-list .disc__head')
    if (head) { await head.click(); await p.waitForTimeout(500) }
    const readBtn = await p.$('.rc__action--primary')
    if (readBtn) { await readBtn.click(); await p.waitForTimeout(900) }

    const info = await p.evaluate(() => {
      const el = document.querySelector('.peek')
      if (!el) return { open: false }
      const r = el.getBoundingClientRect()
      const text = el.querySelector('.peek__text')
      return {
        open: true,
        width: Math.round(r.width),
        ratio: Math.round((r.width / window.innerWidth) * 100),
        textW: text ? Math.round(text.getBoundingClientRect().width) : 0,
        hasMask: !!document.querySelector('.peek-mask'),
      }
    })
    await p.screenshot({ path: '../docs/_shots/fix-peek.png' })

    // 点左侧空白关闭
    await p.mouse.click(150, 500)
    await p.waitForTimeout(700)
    const closed = await p.evaluate(() => !document.querySelector('.peek'))

    return { ...info, closesOnOutsideClick: closed }
  })

  console.log(JSON.stringify(out, null, 2))
})()
