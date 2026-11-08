/**
 * 字体就绪信号。
 *
 * 为什么要单独做一件事：
 * 1) CJK 用可变字体的 unicode-range 分片，只有文档里真实出现的字才会触发下载，
 *    所以必须用 document.fonts.load 显式「预热」需要的族，否则 Canvas 首次绘制
 *    拿到的是回退字形，而画布不会自动重绘。
 * 2) 字体样式是异步引入的（见 index.html），load 必须在样式表应用之后，
 *    否则会 reject 或永远 pending。
 *
 * 超时兜底：字体服务异常时不能让画布永远不画。
 */

const FONT_PROBES = [
  '400 15px "Noto Sans SC Variable"',
  '600 22px "Noto Serif SC Variable"',
  '700 22px "Noto Serif SC Variable"',
  '600 15px "Fraunces"',
  '400 13px "JetBrains Mono"',
] as const

let readyPromise: Promise<void> | null = null
let fontsLoaded = false

export function fontsReady(): Promise<void> {
  readyPromise ??= loadAllFonts()
  return readyPromise
}

export function initFonts(): Promise<void> {
  return fontsReady()
}

export function areFontsLoaded(): boolean {
  return fontsLoaded
}

async function loadAllFonts(): Promise<void> {
  if (typeof document === 'undefined' || !('fonts' in document)) return

  // 字体 CSS 单独打包（CJK 分片 200+ 条 @font-face，不能进主 bundle），
  // 这里动态引入：Vite 会把它拆成独立 CSS 文件，且拿到的是带 hash 的真实 URL。
  await import('../styles/fonts.css').catch(() => undefined)

  const timeout = new Promise<void>((resolve) => setTimeout(resolve, 2000))

  const load = Promise.all(FONT_PROBES.map((probe) => document.fonts.load(probe)))
    .then(() => undefined)
    .catch(() => undefined)

  await Promise.race([load, timeout])

  // 让浏览器完成一次度量计算，避免首个 createElement 测量拿到旧字形宽度
  try {
    await document.fonts.ready
  } catch {
    // 忽略：字体子系统异常不应影响画布绘制
  }

  fontsLoaded = true
}
