const { chromium } = require('playwright');

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  await p.goto('http://127.0.0.1:8010/', { waitUntil: 'networkidle' });
  await p.waitForTimeout(1200);

  const out = [];
  for (let i = 0; i < 8; i++) {
    await p.keyboard.press('Tab');
    // 等 transition 结束再取值，否则拿到的是过渡中间态
    await p.waitForTimeout(320);
    out.push(
      await p.evaluate(() => {
        const a = document.activeElement;
        if (!a || a === document.body) return { none: true };
        const cs = getComputedStyle(a);
        const transparent = cs.boxShadow.startsWith('rgba(0, 0, 0, 0) 0px 0px 0px 0px');
        return {
          tag: a.tagName.toLowerCase(),
          text: (a.textContent || '').trim().slice(0, 10),
          ring: transparent ? 'TRANSPARENT' : 'VISIBLE',
        };
      }),
    );
  }

  console.log(JSON.stringify(out, null, 2));
  await b.close();
})();
