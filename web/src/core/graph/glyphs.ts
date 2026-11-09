import type { GraphNodeType } from '@/core/api/types'

/**
 * 图谱字形：心迹生长（A3 定稿）。
 *
 * 四类节点共用一套 48 × 48 的设计坐标，渲染器会把它换算到以 r 为单位的
 * 节点局部坐标里。这样同一份几何既能画进图谱，也能直接用于图例，
 * 不再维护第二份图标。
 *
 *   会话 → 轨道环：不对称圆角三角主体 + 穿越主体的轨道线 + 两个端点
 *   记忆 → 枝蔓：弯主枝 + 两处短分枝 + 三片带叶脉的小叶
 *   文档 → 卷边纸片：微弧斜顶 + 卷起的折角 + 两道弯折痕
 *   推理 → 纸飞机：左侧短虚线尾迹 + 机身 + 折线
 */

export type GlyphType = GraphNodeType

export type GlyphPartRole =
  | 'body'
  | 'ring'
  | 'trunk'
  | 'branch'
  | 'detail'
  | 'leaf'
  | 'vein'
  | 'trail'
  | 'fold'
  | 'echo'
  | 'orbit'
  | 'faint'

export interface GlyphPart {
  /** 48 × 48 设计坐标中的路径 */
  d: string
  /** 决定填充、线宽与透明度 */
  role: GlyphPartRole
  /** 叶片等局部形状的平移 / 旋转 */
  transform?: string
}

export interface GlyphDot {
  cx: number
  cy: number
  r: number
  opacity?: number
}

export interface GlyphPaths {
  parts: GlyphPart[]
  dots?: GlyphDot[]
  /** 画布用整枚图形（图例仍用 parts，保证 14px 仍可辨） */
  image?: GlyphImage
  /** 视觉半尺寸（相对 r），用于光晕与点击热区 */
  extent: number
}

/** 以 48 × 48 设计坐标放置的整枚 SVG 图形 */
export interface GlyphImage {
  href: string
  x: number
  y: number
  width: number
  height: number
}

/** 叶片：尖头 + 两段弧；坐标以叶柄为原点，叶尖朝上 */
const LEAF = 'M0 0 C-4.2 -4 -4.2 -8 0 -10 C4.2 -8 4.2 -4 0 0 Z'
/** 叶脉：从叶柄内侧到叶尖前 */
const VEIN = 'M0 -1 L0 -8'

/* ---------- 会话：轨道环 ---------- */

function sessionGlyph(): GlyphPaths {
  return {
    parts: [
      {
        role: 'ring',
        d: 'M16 9.6 C22.8 7.8 31.8 9.0 36.4 13.8 C41.0 18.6 41.4 26.8 37.0 32.2 C32.6 37.6 23.4 39.4 17.0 35.8 C10.6 32.2 8.6 24.6 11.4 18.6 C12.6 15.4 14.0 11.6 16 9.6 Z',
      },
      {
        role: 'orbit',
        d: 'M5.4 30.6 C11.2 27.8 18.0 27.4 24.2 29.4 C30.4 31.4 36.8 30.2 42.6 25.4',
      },
    ],
    dots: [
      { cx: 8.1, cy: 29.6, r: 1.55, opacity: 0.78 },
      { cx: 34.6, cy: 16.2, r: 1.5, opacity: 0.78 },
    ],
    image: {
      href: '/brand/graph/session-orbit.svg',
      x: 5,
      y: 7,
      width: 38,
      height: 33.2,
    },
    extent: 1,
  }
}

/* ---------- 记忆：枝蔓 + 三片叶 ---------- */

function memoryGlyph(): GlyphPaths {
  const leaves: { x: number; y: number; rotate: number }[] = [
    { x: 40, y: 11, rotate: 45 },
    { x: 21, y: 21, rotate: 30 },
    { x: 34, y: 26, rotate: 65 },
  ]

  return {
    parts: [
      {
        role: 'trunk',
        d: 'M13 40 C18 33 24 26 30 20 C34 16 37 13 40 11',
      },
      {
        role: 'branch',
        d: 'M23.8 26.2 C23 24 22 22 21 21',
      },
      {
        role: 'branch',
        d: 'M27 23.5 C29 23.7 32 24.5 34 26',
      },
      ...leaves.flatMap<GlyphPart>(({ x, y, rotate }) => {
        const transform = `translate(${x} ${y}) rotate(${rotate})`
        return [
          { role: 'leaf', d: LEAF, transform },
          { role: 'vein', d: VEIN, transform },
        ]
      }),
      { role: 'faint', d: 'M9 42 L14 41' },
    ],
    // 画布使用整枚彩色原图；图例继续用上面的同形线稿（沿用 session-orbit 先例）
    image: {
      href: '/brand/graph/node-reuse-memory.svg',
      x: 0,
      y: 0,
      width: 48,
      height: 48,
    },
    extent: 1,
  }
}

/* ---------- 文档：卷边纸片 ---------- */

function documentGlyph(): GlyphPaths {
  return {
    parts: [
      {
        role: 'body',
        d: 'M10 8 C16 7 24 6 30 5 C35 7 38 10 40 14 V37 L34 42 H10 Z',
      },
      {
        role: 'fold',
        d: 'M30 5 C34 7 37 10 40 14 C37 14 34 14 31 15 C30 12 30 8 30 5 Z',
      },
      {
        role: 'detail',
        d: 'M17 24 C22 22 27 22 31 21 M17 31 C21 30 25 30 27 28',
      },
    ],
    // 知识节点复用用户原图，画布不再绘线稿
    image: {
      href: '/brand/graph/node-reuse-knowledge.svg',
      x: 0,
      y: 0,
      width: 48,
      height: 48,
    },
    extent: 1,
  }
}

/* ---------- 推理：纸飞机 + 左侧短虚线尾迹 ---------- */

function reasonGlyph(): GlyphPaths {
  return {
    parts: [
      {
        role: 'trail',
        d: 'M1 29 C4 28 7 26 11 24',
      },
      {
        role: 'body',
        d: 'M11 9 L45 24 L11 39 L20 26 Z',
      },
      {
        role: 'detail',
        d: 'M20 26 L45 24',
      },
    ],
    // 引导节点复用用户原图，画布不再绘线稿
    image: {
      href: '/brand/graph/node-reuse-guidance.svg',
      x: 0,
      y: 0,
      width: 48,
      height: 48,
    },
    extent: 1,
  }
}

/* ---------- 导出 ---------- */

const CACHE = new Map<GlyphType, GlyphPaths>()

/** 取得字形路径（按类型缓存，纹路是纯几何常量） */
export function glyphFor(type: GlyphType): GlyphPaths {
  let g = CACHE.get(type)
  if (g) return g

  switch (type) {
    case 'session':
      g = sessionGlyph()
      break
    case 'memory':
      g = memoryGlyph()
      break
    case 'document':
      g = documentGlyph()
      break
    case 'reason':
      g = reasonGlyph()
      break
    default:
      g = documentGlyph()
  }
  CACHE.set(type, g)
  return g
}

/** 各类型的默认半径（像素） */
export const GLYPH_RADIUS: Record<GlyphType, number> = {
  session: 26,
  memory: 19,
  document: 17,
  reason: 16,
}

/** 各类型的无障碍中文名 */
export const GLYPH_LABEL: Record<GlyphType, string> = {
  session: '会话',
  memory: '记忆',
  document: '文档',
  reason: '推理',
}
