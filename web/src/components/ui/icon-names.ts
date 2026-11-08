/**
 * 图标名清单 —— 与 src/assets/icons.svg 中的 <symbol id="i-xxx"> 一一对应。
 * 用联合类型约束 AppIcon 的 name，拼错时在编译期报错而不是静默渲染空白。
 */
export const ICON_NAMES = [
  // 导航
  'chat',
  'archive',
  'pen',
  'pulse',
  'search',
  // 方向
  'chevron-right',
  'chevron-down',
  'chevron-up',
  'arrow-up',
  'arrow-down',
  // 操作
  'close',
  'plus',
  'minus',
  'check',
  'refresh',
  'copy',
  'settings',
  'trash',
  'send',
  'stop',
  // 语义
  'tool',
  'compass',
  'route',
  'doc',
  'memory',
  'quote',
  'save',
  'alert',
  'info',
  'sparkle',
  'link',
  'list',
  'filter',
  'maximize',
  'zoom-in',
  'zoom-out',
  'play',
  'clock',
  'calendar',
] as const

export type IconName = (typeof ICON_NAMES)[number]
