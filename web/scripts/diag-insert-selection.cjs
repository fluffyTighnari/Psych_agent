/**
 * 验证「插入选中」：展开全文 → 选中一段 → 点插入 → 检查实际写入周记的内容
 * 这是用户最可能发现问题的功能，必须真的工作。
 */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 } })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))

  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)

  // 切 weekly
  await p.click('.modes .pill:nth-child(2)')
  await p.waitForTimeout(600)

  // 打开摘取
  await p.click('button:has-text("从对话摘取")')
  await p.waitForTimeout(1000)

  const r = {}
  r.candidates = await p.evaluate(() => document.querySelectorAll('.pick__item').length)
  if (r.candidates === 0) {
    console.log(JSON.stringify({ ...r, note: '无候选对话，需先进行咨询', errors }, null, 2))
    await b.close()
    return
  }

  // 展开全文
  const expandBtn = await p.$('.pick__item button:has-text("展开全文")')
  if (expandBtn) { await expandBtn.click(); await p.waitForTimeout(600) }

  r.expanded = await p.evaluate(() => {
    const full = document.querySelector('.pick__full-text')
    return { hasFull: !!full, len: full?.textContent?.length ?? 0, preview: full?.textContent?.slice(0, 40) }
  })

  // 用 JS 精确选中全文中的一段（模拟用户拖选）
  r.selectedText = await p.evaluate(() => {
    const el = document.querySelector('.pick__full-text')
    if (!el || !el.firstChild) return null
    const text = el.textContent || ''
    // 选中间 30 个字符
    const start = Math.min(20, Math.max(0, text.length - 30))
    const end = Math.min(start + 30, text.length)
    const range = document.createRange()
    range.setStart(el.firstChild, start)
    range.setEnd(el.firstChild, end)
    const sel = window.getSelection()
    sel.removeAllRanges()
    sel.addRange(range)
    return sel.toString()
  })

  // 点插入
  const insertBtn = await p.$('.pick__item button:has-text("插入到")')
  if (insertBtn) { await insertBtn.click(); await p.waitForTimeout(800) }

  r.toast = await p.evaluate(() => document.querySelector('.toast')?.textContent?.trim().slice(0, 50) ?? null)

  // 关闭抽屉，检查周记内容
  await p.keyboard.press('Escape')
  await p.waitForTimeout(600)

  r.written = await p.evaluate(() => {
    const editors = [...document.querySelectorAll('.cm-content')]
    return editors.map(e => (e.textContent || '').slice(0, 200))
  })

  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
