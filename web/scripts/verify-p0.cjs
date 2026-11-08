const { chromium } = require('playwright');
const zlib = require('zlib');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const errors = [];
  const failed = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message));
  page.on('response', (r) => {
    if (r.status() >= 400) failed.push(r.status() + ' ' + r.url());
  });

  await page.goto('http://127.0.0.1:8010/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);

  // 1. 应用是否挂载
  const appHtmlLen = await page.evaluate(() => document.getElementById('app')?.innerHTML.length ?? 0);

  // 2. 字体是否真的生效（不是回退）
  const fontCheck = await page.evaluate(() => {
    const el = document.querySelector('.rail__brand-text h1');
    const sub = document.querySelector('.rail__label');
    return {
      brandFont: el ? getComputedStyle(el).fontFamily : null,
      navFont: sub ? getComputedStyle(sub).fontFamily : null,
      loaded: [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family).slice(0, 8),
      serifActive: document.fonts.check('700 22px "Noto Serif SC Variable"'),
      sansActive: document.fonts.check('400 15px "Noto Sans SC Variable"'),
      frauncesActive: document.fonts.check('600 22px "Fraunces"'),
    };
  });

  // 3. 关键令牌是否解析出了真实值（不是空字符串/未定义）
  const tokenCheck = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const pick = (n) => cs.getPropertyValue(n).trim();
    return {
      surface: pick('--surface'),
      textPrimary: pick('--text-primary'),
      textTertiary: pick('--text-tertiary'),
      accent: pick('--accent'),
      accentDeep: pick('--accent-deep'),
      fsBase: pick('--fs-base'),
      sp4: pick('--sp-4'),
      rMd: pick('--r-md'),
      ef1: pick('--ef-1'),
      zModal: pick('--z-modal'),
      focusRing: pick('--focus-ring'),
      fontSerif: pick('--font-serif'),
    };
  });

  // 4. 纸张纹理是否应用到外壳
  const shellCheck = await page.evaluate(() => {
    const el = document.querySelector('.app-shell');
    if (!el) return null;
    const bg = getComputedStyle(el).backgroundImage;
    return { hasNoise: bg.includes('paper-noise') || bg.includes('data:image'), bgSample: bg.slice(0, 90) };
  });

  // 5. 图标 sprite 是否注入且 <use> 能解析
  const iconCheck = await page.evaluate(() => {
    const symbols = document.querySelectorAll('symbol[id^="i-"]');
    const uses = document.querySelectorAll('svg.app-icon use');
    const firstUse = uses[0];
    let resolved = 0;
    uses.forEach((u) => {
      const href = u.getAttribute('href') || u.getAttribute('xlink:href') || '';
      if (href && document.querySelector(href)) resolved++;
    });
    // 取第一个图标的实际渲染尺寸，确认不是 0x0
    const box = firstUse ? firstUse.closest('svg').getBoundingClientRect() : null;
    return {
      symbolCount: symbols.length,
      useCount: uses.length,
      resolved,
      firstIconBox: box ? { w: Math.round(box.width), h: Math.round(box.height) } : null,
    };
  });

  // 6. 导航切换
  const navResults = [];
  for (const [label, hash] of [['过往记录', '#/records'], ['码字编辑', '#/write'], ['流程日志', '#/trace'], ['检索调试', '#/retrieval'], ['主对话', '#/']]) {
    await page.evaluate((h) => { location.hash = h; }, hash);
    await page.waitForTimeout(400);
    const state = await page.evaluate(() => ({
      hash: location.hash,
      title: document.title,
      h2: document.querySelector('.view-head__title h2')?.textContent?.trim(),
      activeNav: document.querySelector('.rail__item.is-active .rail__label')?.textContent?.trim(),
    }));
    navResults.push({ expect: label, ...state });
  }

  // 7. 键盘焦点可达性：Tab 遍历，检查是否有元素获得焦点
  await page.evaluate(() => { location.hash = '#/'; });
  await page.waitForTimeout(300);
  const focusTrail = [];
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press('Tab');
    const info = await page.evaluate(() => {
      const a = document.activeElement;
      if (!a || a === document.body) return null;
      const cs = getComputedStyle(a);
      return {
        tag: a.tagName.toLowerCase(),
        text: (a.textContent || '').trim().slice(0, 12),
        outline: cs.outlineStyle,
        boxShadow: cs.boxShadow.slice(0, 40),
      };
    });
    focusTrail.push(info);
  }

  // 8. 截图
  await page.screenshot({ path: 'docs/_shots/p0-chat.png', fullPage: false });
  await page.evaluate(() => { location.hash = '#/records'; });
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'docs/_shots/p0-records.png' });

  // 9. 窄屏响应式
  await page.setViewportSize({ width: 900, height: 800 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'docs/_shots/p0-narrow.png' });

  console.log(JSON.stringify({
    appHtmlLen,
    fontCheck,
    tokenCheck,
    shellCheck,
    iconCheck,
    navResults,
    focusTrail,
    errors,
    failedRequests: failed,
  }, null, 2));

  await browser.close();
})();
