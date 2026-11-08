/** 富文本实机验证：发一条能触发加粗的请求，确认渲染为真实元素 */
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1680, height: 1000 } })
  const errors = []
  p.on('pageerror', e => errors.push(String(e)))
  await p.goto('http://127.0.0.1:8010/#/', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)

  // 直接注入一段含各种标记的文本到 DOM 不可行（会绕过组件），
  // 改为验证解析器在浏览器环境的正确性 + 检查现有消息的渲染结构
  const r = await p.evaluate(() => {
    const bubbles = [...document.querySelectorAll('.msg--assistant .rt')]
    return {
      bubbleCount: bubbles.length,
      // 各类元素统计
      strong: document.querySelectorAll('.rt__strong').length,
      em: document.querySelectorAll('.rt__em').length,
      code: document.querySelectorAll('.rt__code').length,
      quote: document.querySelectorAll('.rt__quote').length,
      list: document.querySelectorAll('.rt__list').length,
      li: document.querySelectorAll('.rt__li').length,
      paragraphs: document.querySelectorAll('.rt__p').length,
      // 是否有残留的原始标记泄漏到文本节点
      leakedStars: [...document.querySelectorAll('.rt__text')].filter(e => e.textContent.includes('**')).length,
      leakedCites: [...document.querySelectorAll('.rt__text')].filter(e => e.textContent.includes('[[cite:')).length,
      // 样本：第一个 assistant 气泡的前 200 字
      sample: bubbles[0]?.textContent?.slice(0, 200) ?? '',
    }
  })

  // 发一条引导模型用加粗/列表的请求
  await p.fill('.composer__input', '请用加粗标题和编号列表，给我 3 条缓解开会焦虑的具体方法。')
  await p.click('button:has-text("发送")')

  for (let i = 0; i < 200; i++) {
    await p.waitForTimeout(1000)
    const done = await p.evaluate(() => {
      const chains = [...document.querySelectorAll('.chain')]
      return chains.length > 0 && !chains[chains.length - 1].classList.contains('chain--running')
    })
    if (done) break
  }

  const after = await p.evaluate(() => ({
    strong: document.querySelectorAll('.rt__strong').length,
    list: document.querySelectorAll('.rt__list').length,
    li: document.querySelectorAll('.rt__li').length,
    em: document.querySelectorAll('.rt__em').length,
    quote: document.querySelectorAll('.rt__quote').length,
    leakedStars: [...document.querySelectorAll('.rt__text')].filter(e => e.textContent.includes('**')).length,
    chainSummary: document.querySelector('.chain__text')?.textContent?.trim(),
    chainExpanded: !!document.querySelector('.chain__steps'),
  }))

  await p.screenshot({ path: '../docs/_shots/p3-richtext.png' })
  console.log(JSON.stringify({ before: r, after, errors }, null, 2))
  await b.close()
})()
