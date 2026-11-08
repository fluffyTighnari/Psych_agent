/**
 * P1 浏览器验证：API 客户端、UI 原子组件、会话/模型 store、无障碍行为。
 * 需要后端在 http://127.0.0.1:8010 运行（新版挂在根路径）。
 */
const { chromium } = require('playwright')

const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:8010/'

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  const errors = []
  const failed = []
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
  })
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))
  page.on('response', (r) => {
    if (r.status() >= 400) failed.push(r.status() + ' ' + r.url())
  })

  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1800)

  const report = { steps: {} }

  // ---- 1. 会话与模型数据是否真的通了 ----
  report.steps.stores = await page.evaluate(() => ({
    chips: [...document.querySelectorAll('.chip')].map((c) => c.textContent.trim().replace(/\s+/g, ' ')),
    railSession: document.querySelector('.rail__session')?.textContent?.trim() ?? null,
    connText: document.querySelector('.rail__conn-text')?.textContent?.trim() ?? null,
    connOn: !!document.querySelector('.rail__dot.is-on'),
  }))

  // ---- 2. 打开模型抽屉，验证 dialog 语义 + 焦点陷阱 ----
  await page.click('button:has-text("模型设置")')
  await page.waitForTimeout(600)

  report.steps.drawer = await page.evaluate(() => {
    const panel = document.querySelector('.drawer-panel')
    if (!panel) return { open: false }
    const active = document.activeElement
    return {
      open: true,
      role: panel.getAttribute('role'),
      ariaModal: panel.getAttribute('aria-modal'),
      hasLabelledby: !!panel.getAttribute('aria-labelledby'),
      focusInsideDrawer: panel.contains(active),
      slotCount: panel.querySelectorAll('.slot').length,
      driverButtons: panel.querySelectorAll('.slot__driver-btn').length,
      bodyLocked: getComputedStyle(document.body).position === 'fixed',
    }
  })

  // Esc 关闭 + 焦点归还
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)
  report.steps.drawerClose = await page.evaluate(() => ({
    drawerGone: !document.querySelector('.drawer-panel'),
    bodyUnlocked: getComputedStyle(document.body).position !== 'fixed',
    // 焦点应回到「模型设置」按钮
    focusRestoredToTrigger: document.activeElement?.textContent?.includes('模型设置') ?? false,
  }))

  // ---- 3. Toast：触发一次错误提示（保存时未改动 → 按钮禁用；改用一个真实操作） ----
  await page.evaluate(() => {
    // 直接调用模块导出的 toast 不方便，通过 UI 触发：
    // 打开抽屉 → 点「启动」但不选模型
  })

  await page.click('button:has-text("模型设置")')
  await page.waitForTimeout(500)
  // 清空选择后点启动，应触发错误 toast
  await page.evaluate(() => {
    const sel = document.querySelector('.ollama-box__row select')
    if (sel) sel.value = ''
  })
  await page.click('.ollama-box__row button:has-text("启动")')
  await page.waitForTimeout(400)

  report.steps.toast = await page.evaluate(() => {
    const box = document.querySelector('.toasts')
    const items = [...document.querySelectorAll('.toast')]
    return {
      hasLiveRegion: box?.getAttribute('aria-live') ?? null,
      hasRole: box?.getAttribute('role') ?? null,
      count: items.length,
      texts: items.map((t) => t.textContent.trim().slice(0, 24)),
      errorStyled: !!document.querySelector('.toast--err'),
    }
  })

  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)

  // ---- 4. AppDisclosure 与 AppEmpty 可见性（骨架页尚未使用，做存在性检查） ----
  report.steps.componentsBuilt = await page.evaluate(() => {
    // 这些组件在 P2 才会被视图使用；此处确认样式类已随包下发
    const css = [...document.styleSheets]
      .flatMap((s) => {
        try {
          return [...s.cssRules].map((r) => r.cssText)
        } catch {
          return []
        }
      })
      .join('')
    const has = (token) => css.includes(token)
    return {
      tokensLoaded: has('--surface') || has('--accent'),
      hasSkeletonShimmer: has('shimmer'),
      hasFocusVisibleRule: has('focus-visible'),
      hasReducedMotion: has('prefers-reduced-motion'),
    }
  })

  // ---- 5. 键盘可达性全量：从页面顶部 Tab 遍历，记录焦点序列 ----
  await page.evaluate(() => {
    location.hash = '#/'
    document.body.focus()
  })
  await page.waitForTimeout(400)
  const trail = []
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press('Tab')
    await page.waitForTimeout(180)
    trail.push(
      await page.evaluate(() => {
        const a = document.activeElement
        if (!a || a === document.body) return null
        const cs = getComputedStyle(a)
        return {
          tag: a.tagName.toLowerCase(),
          text: (a.textContent || '').trim().slice(0, 12),
          ringVisible: !cs.boxShadow.startsWith('rgba(0, 0, 0, 0) 0px 0px 0px 0px'),
        }
      }),
    )
  }
  report.steps.focusTrail = trail
  report.steps.focusRingAllVisible = trail.filter(Boolean).every((t) => t.ringVisible)

  // ---- 6. 模型 chips 是否随真实数据变化（与 /tool/model 对比） ----
  const apiModels = await page.evaluate(async () => {
    const r = await fetch('/tool/model')
    const j = await r.json()
    return j.code === 200 ? j.data : null
  })
  report.steps.apiVsUi = {
    apiSmall: apiModels?.small?.driver + '/' + (apiModels?.small?.driver === 'ollama' ? apiModels?.small?.ollama_name : apiModels?.small?.api_model_name),
    uiChips: report.steps.stores.chips,
  }

  // ---- 7. 错误处理：请求一个不存在的业务路径，确认 ApiError 分支 ----
  report.steps.apiError = await page.evaluate(async () => {
    // 后端对未知路由返回 404 纯文本/JSON detail，客户端应给出可读错误而非静默
    try {
      const r = await fetch('/tool/search/meta-filter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_type: 'invalid_type' }),
      })
      const j = await r.json()
      return { httpStatus: r.status, code: j.code, msg: String(j.msg).slice(0, 40) }
    } catch (e) {
      return { error: String(e) }
    }
  })

  await page.screenshot({ path: '../docs/_shots/p1-chat.png' })

  report.errors = errors
  report.failedRequests = failed
  console.log(JSON.stringify(report, null, 2))

  await browser.close()
})()
