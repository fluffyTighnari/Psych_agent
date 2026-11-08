const { chromium } = require('playwright')

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))

  await page.goto('http://127.0.0.1:8010/', { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)

  const report = {}

  // ---- 1. 破坏性操作按钮存在且语义正确 ----
  report.buttons = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.view-head__actions button')].map((b) => ({
      text: b.textContent.trim(),
      danger: b.className.includes('c-btn--danger'),
      disabled: b.disabled,
    }))
    return btns
  })

  // ---- 2. 点「重置会话」→ 自定义确认弹窗（非原生 confirm） ----
  await page.click('button:has-text("重置会话")')
  await page.waitForTimeout(500)

  report.confirmDialog = await page.evaluate(() => {
    const card = document.querySelector('.modal-card')
    if (!card) return { open: false }
    return {
      open: true,
      role: card.getAttribute('role'),
      ariaModal: card.getAttribute('aria-modal'),
      title: card.querySelector('.modal-card__title')?.textContent?.trim(),
      message: card.querySelector('.confirm__msg')?.textContent?.trim().slice(0, 50),
      // 危险操作的确认按钮应为 danger 变体
      confirmBtnDanger: !!card.querySelector('.c-btn--danger'),
      focusInside: card.contains(document.activeElement),
      bodyLocked: getComputedStyle(document.body).position === 'fixed',
    }
  })

  // ---- 3. 焦点陷阱：在弹窗内 Tab 循环，不应逃逸 ----
  const trapTrail = []
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press('Tab')
    await page.waitForTimeout(150)
    trapTrail.push(
      await page.evaluate(() => {
        const card = document.querySelector('.modal-card')
        const a = document.activeElement
        return {
          text: (a?.textContent || '').trim().slice(0, 10),
          inside: card ? card.contains(a) : false,
        }
      }),
    )
  }
  report.focusTrap = { trail: trapTrail, allInside: trapTrail.every((t) => t.inside) }

  // ---- 4. Esc 关闭 + 焦点归还 ----
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)
  report.escClose = await page.evaluate(() => ({
    closed: !document.querySelector('.modal-card'),
    bodyUnlocked: getComputedStyle(document.body).position !== 'fixed',
    focusBackOnTrigger: document.activeElement?.textContent?.includes('重置会话') ?? false,
  }))

  // ---- 5. 清空会话按钮：会话为空时应禁用 ----
  report.clearDisabledWhenEmpty = await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.view-head__actions button')].find((b) =>
      b.textContent.includes('清空会话'),
    )
    return btn ? btn.disabled : null
  })

  // ---- 6. 模型抽屉内的表单控件可聚焦（曾经 display:none 的问题） ----
  await page.click('button:has-text("模型设置")')
  await page.waitForTimeout(600)
  report.drawerForms = await page.evaluate(() => {
    const panel = document.querySelector('.drawer-panel')
    if (!panel) return null
    const selects = [...panel.querySelectorAll('select')]
    const inputs = [...panel.querySelectorAll('input')]
    return {
      selectCount: selects.length,
      inputCount: inputs.length,
      // 是否有被 display:none 隐藏但仍需要键盘访问的控件
      hiddenFocusable: [...selects, ...inputs].filter((el) => {
        const cs = getComputedStyle(el)
        return cs.display === 'none' || cs.visibility === 'hidden'
      }).length,
      slotDriverPressed: [...panel.querySelectorAll('.slot__driver-btn')].map((b) =>
        b.getAttribute('aria-pressed'),
      ),
    }
  })

  await page.screenshot({ path: '../docs/_shots/p1-confirm.png' })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)

  report.errors = errors
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
})()
