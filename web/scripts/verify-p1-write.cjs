const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1440, height: 980 } })
  const errors = []
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  p.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))

  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(1500)
  const r = {}

  r.initial = await p.evaluate(() => ({
    modePills: [...document.querySelectorAll('.modes .pill')].map(x => ({ t: x.textContent.trim(), pressed: x.getAttribute('aria-pressed') })),
    charCount: document.querySelector('.meta-bar__stat')?.textContent?.trim(),
    saveDisabled: [...document.querySelectorAll('.actions button')].find(b => b.textContent.includes('保存'))?.disabled,
    dateDefault: document.querySelector('.date-input')?.value,
  }))

  // 输入正文 → 字数更新 → 保存按钮启用
  await p.fill('.editor', '今天试着把手机放进抽屉，一开始确实轻松，但晚上又忍不住打开了视频网站。')
  await p.waitForTimeout(600)
  r.afterType = await p.evaluate(() => ({
    charCount: document.querySelector('.meta-bar__stat')?.textContent?.trim(),
    saveDisabled: [...document.querySelectorAll('.actions button')].find(b => b.textContent.includes('保存'))?.disabled,
  }))

  // 等草稿自动保存（2s 防抖）
  await p.waitForTimeout(2600)
  r.draft = await p.evaluate(() => ({
    statusText: document.querySelector('.meta-bar__status')?.textContent?.trim(),
    inStorage: !!localStorage.getItem('psy:draft'),
  }))

  // 切到 Weekly
  await p.click('.modes .pill:nth-child(2)')
  await p.waitForTimeout(500)
  r.weekly = await p.evaluate(() => ({
    sections: [...document.querySelectorAll('.weekly-sec__name')].map(x => x.textContent.trim()),
    fillIndicator: document.querySelector('.meta-bar__fill')?.textContent?.trim(),
    filledStates: [...document.querySelectorAll('.weekly-sec__state')].map(x => x.textContent.trim()),
    saveDisabled: [...document.querySelectorAll('.actions button')].find(b => b.textContent.includes('保存'))?.disabled,
  }))

  // 填一段 → 完成度更新
  const tas = await p.$$('.weekly-sec textarea')
  if (tas[0]) await tas[0].fill('总觉得自己不够好，做事前先想别人会怎么评价。')
  await p.waitForTimeout(400)
  r.weeklyPartial = await p.evaluate(() => ({
    fillIndicator: document.querySelector('.meta-bar__fill')?.textContent?.trim(),
    filledStates: [...document.querySelectorAll('.weekly-sec__state')].map(x => x.textContent.trim()),
  }))

  // 重新加载 → 草稿恢复
  await p.reload({ waitUntil: 'networkidle' })
  await p.waitForTimeout(1600)
  r.restore = await p.evaluate(() => ({
    activeMode: [...document.querySelectorAll('.modes .pill')].find(x => x.getAttribute('aria-pressed') === 'true')?.textContent?.trim(),
    firstSectionValue: document.querySelector('.weekly-sec textarea')?.value?.slice(0, 20) ?? '',
    toast: document.querySelector('.toast')?.textContent?.trim().slice(0, 20) ?? null,
  }))

  await p.screenshot({ path: '../docs/_shots/p1-write.png' })
  r.errors = errors
  console.log(JSON.stringify(r, null, 2))
  await b.close()
})()
