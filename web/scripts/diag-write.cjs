const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 } })
  const p = await ctx.newPage()
  const r = {}

  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2200)

  // ---- 1. 清空后草稿是否残留 ----
  await p.click('.cm-content')
  await p.keyboard.type('临时内容稍后全删')
  await p.waitForTimeout(2600)
  r.afterType = await p.evaluate(() => ({
    storage: localStorage.getItem('psy:draft') ? 'HAS_DRAFT' : 'EMPTY',
    charCount: document.querySelector('.meta-bar__stat')?.textContent?.trim(),
  }))

  // 全选删除
  await p.keyboard.down('Control'); await p.keyboard.press('a'); await p.keyboard.up('Control')
  await p.keyboard.press('Delete')
  await p.waitForTimeout(2800)
  r.afterDelete = await p.evaluate(() => {
    const raw = localStorage.getItem('psy:draft')
    let content = null
    try { content = raw ? JSON.parse(raw).content : null } catch {}
    return {
      storage: raw ? 'HAS_DRAFT' : 'EMPTY',
      draftContent: content,
      charCount: document.querySelector('.meta-bar__stat')?.textContent?.trim(),
    }
  })

  // 切走再切回，看是否恢复
  await p.evaluate(() => { location.hash = '#/records' })
  await p.waitForTimeout(800)
  await p.evaluate(() => { location.hash = '#/write' })
  await p.waitForTimeout(1500)
  r.afterReturn = await p.evaluate(() => ({
    editorText: document.querySelector('.cm-content')?.textContent ?? '',
    charCount: document.querySelector('.meta-bar__stat')?.textContent?.trim(),
    toast: document.querySelector('.toast')?.textContent?.trim().slice(0, 30) ?? null,
  }))

  // ---- 2. 专注模式滚动 + 保存按钮 ----
  await p.fill('.cm-content', '')
  await p.click('.cm-content')
  for (let i = 0; i < 40; i++) await p.keyboard.type('专注模式滚动测试第' + (i + 1) + '行内容。\n')
  await p.waitForTimeout(600)

  await p.click('button:has-text("专注")')
  await p.waitForTimeout(800)

  r.focusMode = await p.evaluate(() => {
    const view = document.querySelector('.app-view')
    const wrap = document.querySelector('.editor-wrap')
    const cs = view ? getComputedStyle(view) : null
    const wcs = wrap ? getComputedStyle(wrap) : null
    return {
      viewOverflowY: cs?.overflowY,
      viewScrollable: view ? view.scrollHeight > view.clientHeight + 2 : false,
      viewScrollHeight: view?.scrollHeight,
      viewClientHeight: view?.clientHeight,
      wrapOverflowY: wcs?.overflowY,
      wrapScrollable: wrap ? wrap.scrollHeight > wrap.clientHeight + 2 : false,
      docScrollable: document.documentElement.scrollHeight > document.documentElement.clientHeight,
      bodyOverflow: getComputedStyle(document.body).overflow,
    }
  })

  // 保存按钮是否可用
  r.saveBtn = await p.evaluate(() => {
    const btns = [...document.querySelectorAll('.focus-bar button')]
    const save = btns.find(b => b.textContent.includes('保存'))
    return {
      exists: !!save,
      disabled: save?.disabled,
      text: save?.textContent?.trim(),
    }
  })

  // 尝试滚动
  const before = await p.evaluate(() => {
    const el = document.querySelector('.cm-scroller')
    return el?.scrollTop ?? 0
  })
  await p.mouse.move(750, 500)
  await p.mouse.wheel(0, 600)
  await p.waitForTimeout(500)
  const after = await p.evaluate(() => {
    const el = document.querySelector('.cm-scroller')
    return {
      scrollTop: el?.scrollTop ?? 0,
      scrollHeight: el?.scrollHeight,
      clientHeight: el?.clientHeight,
    }
  })
  r.scrollTest = { before, ...after, scrolled: after.scrollTop > before }

  await p.screenshot({ path: '../docs/_shots/diag-focus-scroll.png' })
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
