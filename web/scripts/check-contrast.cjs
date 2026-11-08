// 对比度核算：验证设计文档 §5.3 列出的四处修正在实际渲染中成立
function lum(hex) {
  const c = hex.replace('#','');
  const rgb = [0,2,4].map(i => {
    const v = parseInt(c.slice(i, i+2), 16) / 255;
    return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4);
  });
  return 0.2126*rgb[0] + 0.7152*rgb[1] + 0.0722*rgb[2];
}
function ratio(a, b) {
  const L1 = lum(a), L2 = lum(b);
  const [hi, lo] = L1 > L2 ? [L1, L2] : [L2, L1];
  return (hi + 0.05) / (lo + 0.05);
}

const surface = '#f4efe4';       // --surface
const surfaceRaised = '#faf6ec'; // --surface-raised
const cases = [
  ['小字提示 text-tertiary on surface',        '#746750', surface,       4.5],
  ['小字提示 text-tertiary on surface-raised', '#746750', surfaceRaised, 4.5],
  ['次级正文 text-secondary on surface',       '#6c5f4e', surface,       4.5],
  ['正文 text-primary on surface',             '#2a231c', surface,       4.5],
  ['小号红字 accent-deep on surface',          '#a03820', surface,       4.5],
  ['小号红字 accent-deep on surface-raised',   '#a03820', surfaceRaised, 4.5],
  ['主按钮文字 on accent',                     '#fff7ee', '#c24a2e',    4.5],
  ['主按钮文字 on accent-deep(hover)',         '#fff7ee', '#a03820',    4.5],
  ['旧值 accent 裸用（应不达标，仅≥17px 可用）', '#c24a2e', surface,      4.5],
  ['旧值 ink-faint（应不达标，已废弃）',        '#a89a86', surface,       4.5],
];

let pass = 0, fail = 0;
for (const [name, fg, bg, min] of cases) {
  const r = ratio(fg, bg);
  const ok = r >= min;
  const tag = ok ? 'PASS' : 'FAIL';
  if (ok) pass++; else fail++;
  console.log(`${tag}  ${r.toFixed(2)}:1  (>=${min})  ${name}`);
}
console.log(`\n${pass} pass / ${fail} fail`);
