/**
 * P4 验证：CodeMirror 编辑器、草稿、预览、从对话摘取、保存落盘。
 */
const { chromium } = require('playwright')

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })
  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))

  const r = {}

  await page.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)

  // 1. CodeMirror 是否挂载
  r.editor = await page.evaluate(() => {
    const cm = document.querySelector('.cm-editor')
    const content = document.querySelector('.cm-content')
    return {
      mounted: !!cm,
      hasLineNumbers: !!document.querySelector('.cm-gutters'),
      hasContent: !!content,
      ariaLabel: content?.getAttribute('aria-label') ?? null,
      editable: content?.getAttribute('contenteditable'),
    }
  })

  // 2. 输入内容 → 字数更新
  await page.click('.cm-content')
  await page.keyboard.type('今天试着把手机放进抽屉，一开始确实轻松。')
  await page.waitForTimeout(600)

  r.typing = await page.evaluate(() => ({
    charCount: document.querySelector('.meta-bar__stat')?.textContent?.trim(),
    saveEnabled: ![...document.querySelectorAll('.actions button')].find((b) => b.textContent.includes('保存'))?.disabled,
    cmText: document.querySelector('.cm-content')?.textContent?.slice(0, 30),
  }))

  // 3. 草稿自动保存
  await page.waitForTimeout(2600)
  r.draft = await page.evaluate(() => ({
    status: document.querySelector('.meta-bar__status')?.textContent?.trim(),
    inStorage: !!localStorage.getItem('psy:draft'),
  }))

  // 4. 切到 Weekly
  await page.click('.modes .pill:nth-child(2)')
  await page.waitForTimeout(800)
  r.weekly = await page.evaluate(() => ({
    sections: [...document.querySelectorAll('.weekly-sec__name')].map((x) => x.textContent.trim()),
    editors: document.querySelectorAll('.cm-editor').length,
    fillIndicator: document.querySelector('.meta-bar__fill')?.textContent?.trim(),
    pickButtons: document.querySelectorAll('.weekly-sec__pick').length,
  }))

  // 5. 从对话摘取面板
  await page.click('button:has-text("从对话摘取")')
  await page.waitForTimeout(900)
  r.pick = await page.evaluate(() => {
    const drawer = document.querySelector('.drawer-panel')
    if (!drawer) return { open: false }
    return {
      open: true,
      title: drawer.querySelector('.drawer-panel__title')?.textContent?.trim(),
      targets: [...drawer.querySelectorAll('.pick__target-btn')].map((x) => x.textContent.trim()),
      candidates: drawer.querySelectorAll('.pick__item').length,
      kinds: [...drawer.querySelectorAll('.pick__kind')].slice(0, 4).map((x) => x.textContent.trim()),
      empty: !!drawer.querySelector('.empty'),
    }
  })

  // 若有候选，插入一条到 solution
  const solutionBtn = await page.$('.pick__target-btn:nth-child(3)')
  if (solutionBtn) {
    await solutionBtn.click()
    await page.waitForTimeout(300)
    const insertBtn = await page.$('.pick__item button')
    if (insertBtn) {
      await insertBtn.click()
      await page.waitForTimeout(700)
    }
  }

  r.afterInsert = await page.evaluate(() => ({
    insertToast: document.querySelector('.toast')?.textContent?.trim().slice(0, 30) ?? null,
  }))

  // 关闭抽屉
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)

  r.afterInsertSections = await page.evaluate(() => ({
    filled: [...document.querySelectorAll('.weekly-sec__state')].map((x) => x.textContent.trim()),
    fillIndicator: document.querySelector('.meta-bar__fill')?.textContent?.trim(),
    solutionHasQuote: [...document.querySelectorAll('.cm-content')].some((c) => c.textContent.includes('>')),
  }))

  // 6. 预览
  await page.click('button:has-text("预览")')
  await page.waitForTimeout(700)
  r.preview = await page.evaluate(() => {
    const modal = document.querySelector('.modal-card')
    return {
      open: !!modal,
      title: modal?.querySelector('.modal-card__title')?.textContent?.trim(),
      hasRt: !!modal?.querySelector('.rt'),
      headings: modal?.querySelectorAll('.rt__h').length ?? 0,
      textLen: modal?.querySelector('.preview')?.textContent?.length ?? 0,
    }
  })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)

  // 7. 专注模式
  await page.click('button:has-text("专注")')
  await page.waitForTimeout(600)
  r.focusMode = await page.evaluate(() => ({
    hasFocusBar: !!document.querySelector('.focus-bar'),
    headerHidden: !document.querySelector('.view-head'),
    wrapIsNarrow: !!document.querySelector('.editor-wrap.is-focus'),
  }))
  const exitBtn = await page.$('.focus-bar button')
  if (exitBtn) await exitBtn.click()
  await page.waitForTimeout(500)

  await page.screenshot({ path: '../docs/_shots/p4-write.png' })

  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await browser.close()
})()
