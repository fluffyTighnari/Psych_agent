const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 })

  // 1. 编辑页聚焦
  await p.goto('http://127.0.0.1:8010/#/write', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  await p.click('.cm-content')
  await p.keyboard.type('测试聚焦红线')
  await p.waitForTimeout(500)

  const editorInfo = await p.evaluate(() => {
    const gutters = document.querySelector('.cm-gutters')
    const activeGutter = document.querySelector('.cm-activeLineGutter')
    const cursor = document.querySelector('.cm-cursor')
    const s = (el) => el ? getComputedStyle(el) : null
    return {
      gutterCount: document.querySelectorAll('.cm-gutters').length,
      gutterBorder: s(gutters)?.borderRight || s(gutters)?.borderLeft,
      gutterBg: s(gutters)?.backgroundColor,
      activeGutterColor: activeGutter ? s(activeGutter).color : null,
      activeGutterBorder: activeGutter ? s(activeGutter).borderLeft || s(activeGutter).borderRight : null,
      cursorBorderLeft: cursor ? s(cursor).borderLeftColor : null,
      cursorWidth: cursor ? s(cursor).borderLeftWidth : null,
      // 编辑器宽度
      editorW: Math.round(document.querySelector('.md-editor')?.getBoundingClientRect().width ?? 0),
      wrapW: Math.round(document.querySelector('.editor-wrap')?.getBoundingClientRect().width ?? 0),
    }
  })

  const ed = await p.$('.md-editor')
  if (ed) await ed.screenshot({ path: '../docs/_shots/diag-editor-focus.png' })

  // 2. 专注模式
  await p.click('button:has-text("专注")')
  await p.waitForTimeout(700)
  const focusInfo = await p.evaluate(() => ({
    wrapW: Math.round(document.querySelector('.editor-wrap')?.getBoundingClientRect().width ?? 0),
    editorW: Math.round(document.querySelector('.md-editor')?.getBoundingClientRect().width ?? 0),
    viewW: Math.round(document.querySelector('.app-view')?.getBoundingClientRect().width ?? 0),
  }))
  await p.screenshot({ path: '../docs/_shots/diag-focus-mode.png' })

  // 3. 记录页滚动
  await p.goto('http://127.0.0.1:8010/#/records', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  const scrollInfo = await p.evaluate(() => {
    const view = document.querySelector('.app-view')
    const results = document.querySelector('.results')
    const form = document.querySelector('.filter-form')
    return {
      viewScrollable: view ? view.scrollHeight > view.clientHeight + 2 : false,
      viewOverflow: view ? getComputedStyle(view).overflowY : null,
      resultsOverflow: results ? getComputedStyle(results).overflowY : null,
      resultsHeight: results ? Math.round(results.getBoundingClientRect().height) : 0,
      formHeight: form ? Math.round(form.getBoundingClientRect().height) : 0,
      viewHeight: view ? Math.round(view.getBoundingClientRect().height) : 0,
      // 正文字体
      summaryFont: document.querySelector('.rc__summary') ? getComputedStyle(document.querySelector('.rc__summary')).fontSize : null,
    }
  })
  await p.screenshot({ path: '../docs/_shots/diag-records.png' })

  // 4. 图谱尺寸与 Inspector
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(3500)
  const graphInfo = await p.evaluate(() => ({
    stageW: Math.round(document.querySelector('.gc__stage')?.getBoundingClientRect().width ?? 0),
    stageH: Math.round(document.querySelector('.gc__stage')?.getBoundingClientRect().height ?? 0),
    paneW: Math.round(document.querySelector('.graph-pane')?.getBoundingClientRect().width ?? 0),
    chatW: Math.round(document.querySelector('.chat-scroll')?.getBoundingClientRect().width ?? 0),
  }))

  console.log(JSON.stringify({ editorInfo, focusInfo, scrollInfo, graphInfo }, null, 2))
  await b.close()
})()
