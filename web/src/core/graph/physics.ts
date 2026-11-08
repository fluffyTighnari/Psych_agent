import type { GraphLink, GraphNode, RelationType } from '@/core/api/types'
import { GLYPH_RADIUS } from './glyphs'

/**
 * 力导向物理模拟。
 *
 * 相比旧版（app.js 的 tick()）的三个关键改进：
 * 1) **Barnes-Hut 四叉树**：节点 ≥ 80 时用 O(n log n) 近似替代 O(n²) 双重循环；
 * 2) **按关系类型区分弹簧长度**：会话→文档比记忆→文档更远，结构语义才能读出来；
 * 3) **按类型分层初始化**：会话在中心、记忆在内圈、文档在外圈，避免随机撒点后长时间震荡。
 */

export interface SimNode {
  id: string
  name: string
  type: GraphNode['type']
  summary?: string
  source?: string
  x: number
  y: number
  vx: number
  vy: number
  r: number
  /** 度数，决定绘制尺寸与标签优先级 */
  degree: number
  /** 拖拽时固定 */
  fx: number | null
  fy: number | null
  /** 入场动画进度 0→1 */
  appear: number
}

export interface SimLink {
  source: SimNode
  target: SimNode
  relation: RelationType
}

/* ---------- 力的参数 ---------- */

const REPULSION = 4800
const CENTER_STRENGTH = 0.008
const DAMPING = 0.88
const MAX_VELOCITY = 18

/** 不同关系的理想边长：语义越"远"，边长越长 */
const LINK_LENGTH: Record<RelationType, number> = {
  session_bind_memory: 130,
  session_ref_doc: 200,
  memory_ref_doc: 110,
  memory_related_memory: 95,
  reason_next: 90,
  session_bind_reason: 150,
}

const BARNES_HUT_THRESHOLD = 80
const THETA = 0.9

/* ---------- 四叉树 ---------- */

interface QuadNode {
  x: number
  y: number
  size: number
  mass: number
  cx: number
  cy: number
  children: QuadNode[] | null
  body: SimNode | null
}

function createQuad(x: number, y: number, size: number): QuadNode {
  return { x, y, size, mass: 0, cx: 0, cy: 0, children: null, body: null }
}

function quadContains(q: QuadNode, n: SimNode): boolean {
  return (
    n.x >= q.x - q.size / 2 &&
    n.x < q.x + q.size / 2 &&
    n.y >= q.y - q.size / 2 &&
    n.y < q.y + q.size / 2
  )
}

function subdivide(q: QuadNode): void {
  const half = q.size / 2
  const quarter = q.size / 4
  q.children = [
    createQuad(q.x - quarter, q.y - quarter, half),
    createQuad(q.x + quarter, q.y - quarter, half),
    createQuad(q.x - quarter, q.y + quarter, half),
    createQuad(q.x + quarter, q.y + quarter, half),
  ]
}

function quadInsert(q: QuadNode, n: SimNode, depth: number): void {
  if (depth > 12) return

  if (!q.children && q.body === null) {
    q.body = n
    return
  }

  if (!q.children) {
    const existing = q.body
    q.body = null
    subdivide(q)
    if (existing) {
      for (const c of q.children!) {
        if (quadContains(c, existing)) {
          quadInsert(c, existing, depth + 1)
          break
        }
      }
    }
  }

  for (const c of q.children!) {
    if (quadContains(c, n)) {
      quadInsert(c, n, depth + 1)
      return
    }
  }
  // 落在边界上（浮点误差）：挂到第一个子节点，避免丢失
  quadInsert(q.children![0]!, n, depth + 1)
}

function accumulate(q: QuadNode): void {
  if (!q.children) {
    if (q.body) {
      q.mass = 1
      q.cx = q.body.x
      q.cy = q.body.y
    }
    return
  }
  let mass = 0
  let cx = 0
  let cy = 0
  for (const c of q.children) {
    accumulate(c)
    mass += c.mass
    cx += c.cx * c.mass
    cy += c.cy * c.mass
  }
  q.mass = mass
  if (mass > 0) {
    q.cx = cx / mass
    q.cy = cy / mass
  }
}

function applyQuadForce(q: QuadNode, n: SimNode, acc: { x: number; y: number }): void {
  if (q.mass === 0) return

  // 叶子：直接作用（跳过自身）
  if (!q.children) {
    if (q.body && q.body !== n) repel(n, q.body.x, q.body.y, acc)
    return
  }

  const dx = q.cx - n.x
  const dy = q.cy - n.y
  const d2 = dx * dx + dy * dy
  const d = Math.sqrt(d2) || 1

  // 足够远：整体当作一个质点
  if ((q.size / d) < THETA) {
    const f = (REPULSION * q.mass) / Math.max(d2, 1)
    acc.x -= (dx / d) * f
    acc.y -= (dy / d) * f
    return
  }

  for (const c of q.children) applyQuadForce(c, n, acc)
}

function repel(n: SimNode, ox: number, oy: number, acc: { x: number; y: number }): void {
  let dx = ox - n.x
  let dy = oy - n.y
  let d2 = dx * dx + dy * dy
  if (d2 < 1) d2 = 1
  const d = Math.sqrt(d2)
  const f = REPULSION / d2
  acc.x -= (dx / d) * f
  acc.y -= (dy / d) * f
}

/* ---------- 模拟 ---------- */

export class ForceSimulation {
  nodes: SimNode[] = []
  links: SimLink[] = []
  width = 0
  height = 0

  private usesBarnesHut = false

  setData(data: { nodes: GraphNode[]; links: GraphLink[] }, width: number, height: number): void {
    this.width = width
    this.height = height

    // 保留已有节点的位置，避免每次刷新都重排
    const prev = new Map(this.nodes.map((n) => [n.id, n]))

    const degree = new Map<string, number>()
    for (const l of data.links) {
      degree.set(l.source, (degree.get(l.source) ?? 0) + 1)
      degree.set(l.target, (degree.get(l.target) ?? 0) + 1)
    }

    const nodeMap = new Map<string, SimNode>()
    this.nodes = data.nodes.map((raw) => {
      const old = prev.get(raw.id)
      const deg = degree.get(raw.id) ?? 0
      // 半径来自 glyph 定义（比 Canvas 版整体上调一档，踪迹需要呼吸空间）
      const baseR = GLYPH_RADIUS[raw.type] ?? 14

      const node: SimNode = {
        id: raw.id,
        name: raw.name,
        type: raw.type,
        // exactOptionalPropertyTypes 关闭，undefined 可显式赋值
        summary: raw.summary,
        source: raw.source,
        x: old?.x ?? 0,
        y: old?.y ?? 0,
        vx: 0,
        vy: 0,
        r: Math.min(baseR + deg * 1.4, baseR + 8),
        degree: deg,
        fx: null,
        fy: null,
        appear: old ? 1 : 0,
      }
      nodeMap.set(raw.id, node)
      return node
    })

    // 新节点才做分层初始化
    this.seedNewNodes(nodeMap)

    this.links = data.links
      .map((l) => {
        const s = nodeMap.get(l.source)
        const t = nodeMap.get(l.target)
        return s && t ? { source: s, target: t, relation: l.relation } : null
      })
      .filter((l): l is SimLink => l !== null)

    this.usesBarnesHut = this.nodes.length >= BARNES_HUT_THRESHOLD
  }

  /**
   * 按类型分层撒点：会话在中心、记忆第一圈、文档第二圈（半径按度数）、推理在右侧弧线。
   * 纯随机会让布局震荡很久才稳定。
   */
  private seedNewNodes(nodeMap: Map<string, SimNode>): void {
    const cx = this.width / 2
    const cy = this.height / 2
    const fresh = this.nodes.filter((n) => n.appear === 0)

    let memoryIdx = 0
    let docIdx = 0
    let reasonIdx = 0

    for (const n of fresh) {
      switch (n.type) {
        case 'session':
          n.x = cx
          n.y = cy
          break
        case 'memory': {
          const a = memoryIdx * 2.399963 + 0.7 // 黄金角，分布均匀
          const r = 110 + memoryIdx * 6
          n.x = cx + Math.cos(a) * r
          n.y = cy + Math.sin(a) * r
          memoryIdx++
          break
        }
        case 'document': {
          const a = docIdx * 2.399963
          // 度数高的文档更靠外（被引用多 = 更外围的知识源）
          const r = 190 + Math.min(n.degree * 12, 70) + docIdx * 3
          n.x = cx + Math.cos(a) * r
          n.y = cy + Math.sin(a) * r
          docIdx++
          break
        }
        case 'reason': {
          // 推理链走右侧弧线，与关联网络在空间上分开
          const a = -Math.PI / 3 + reasonIdx * 0.32
          n.x = cx + Math.cos(a) * 180
          n.y = cy + Math.sin(a) * 180
          reasonIdx++
          break
        }
      }
    }

    void nodeMap
  }

  /** 推进一步，返回本帧总位移（用于自动停帧判断） */
  step(): number {
    const nodes = this.nodes
    if (!nodes.length) return 0

    const cx = this.width / 2
    const cy = this.height / 2

    // 斥力
    if (this.usesBarnesHut) {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
      for (const n of nodes) {
        if (n.x < minX) minX = n.x
        if (n.x > maxX) maxX = n.x
        if (n.y < minY) minY = n.y
        if (n.y > maxY) maxY = n.y
      }
      const size = Math.max(maxX - minX, maxY - minY) * 1.2 || 100
      const root = createQuad((minX + maxX) / 2, (minY + maxY) / 2, size)
      for (const n of nodes) quadInsert(root, n, 0)
      accumulate(root)

      const acc = { x: 0, y: 0 }
      for (const n of nodes) {
        acc.x = 0
        acc.y = 0
        applyQuadForce(root, n, acc)
        n.vx += acc.x
        n.vy += acc.y
      }
    } else {
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i]!
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j]!
          let dx = b.x - a.x
          let dy = b.y - a.y
          let d2 = dx * dx + dy * dy
          if (d2 < 1) d2 = 1
          const d = Math.sqrt(d2)
          const f = REPULSION / d2
          const fx = (dx / d) * f
          const fy = (dy / d) * f
          a.vx -= fx
          a.vy -= fy
          b.vx += fx
          b.vy += fy
        }
      }
    }

    // 弹簧
    for (const l of this.links) {
      const { source: a, target: b } = l
      const dx = b.x - a.x
      const dy = b.y - a.y
      const d = Math.sqrt(dx * dx + dy * dy) || 1
      const rest = LINK_LENGTH[l.relation] ?? 140
      const f = (d - rest) * 0.03
      const fx = (dx / d) * f
      const fy = (dy / d) * f
      if (a.fx === null) {
        a.vx += fx
        a.vy += fy
      }
      if (b.fx === null) {
        b.vx -= fx
        b.vy -= fy
      }
    }

    // 向心 + 阻尼 + 边界
    let totalMovement = 0
    for (const n of nodes) {
      // 入场动画
      if (n.appear < 1) n.appear = Math.min(1, n.appear + 0.06)

      if (n.fx !== null && n.fy !== null) {
        n.vx = 0
        n.vy = 0
        n.x = n.fx
        n.y = n.fy
        continue
      }

      n.vx += (cx - n.x) * CENTER_STRENGTH
      n.vy += (cy - n.y) * CENTER_STRENGTH
      n.vx *= DAMPING
      n.vy *= DAMPING

      // 限速：防止初始撒点距离过大时速度爆炸
      const speed = Math.hypot(n.vx, n.vy)
      if (speed > MAX_VELOCITY) {
        n.vx = (n.vx / speed) * MAX_VELOCITY
        n.vy = (n.vy / speed) * MAX_VELOCITY
      }

      n.x += n.vx
      n.y += n.vy
      n.x = Math.max(n.r, Math.min(this.width - n.r, n.x))
      n.y = Math.max(n.r, Math.min(this.height - n.r, n.y))

      totalMovement += Math.abs(n.vx) + Math.abs(n.vy)
    }

    return totalMovement
  }

  /** 一次性把布局跑到稳定（reduced-motion 与首帧用） */
  settle(iterations = 200): void {
    for (let i = 0; i < iterations; i++) {
      this.step()
      // 最后一轮把入场动画直接拉满
      if (i === iterations - 1) for (const n of this.nodes) n.appear = 1
    }
  }

  /** 邻接表：聚焦高亮用 */
  adjacency(): Map<string, Set<string>> {
    const map = new Map<string, Set<string>>()
    for (const l of this.links) {
      if (!map.has(l.source.id)) map.set(l.source.id, new Set())
      if (!map.has(l.target.id)) map.set(l.target.id, new Set())
      map.get(l.source.id)!.add(l.target.id)
      map.get(l.target.id)!.add(l.source.id)
    }
    return map
  }

  findNode(x: number, y: number): SimNode | null {
    // 从后往前找：后绘制的在上层
    for (let i = this.nodes.length - 1; i >= 0; i--) {
      const n = this.nodes[i]!
      const dx = x - n.x
      const dy = y - n.y
      const hitR = n.r + 6
      if (dx * dx + dy * dy <= hitR * hitR) return n
    }
    return null
  }
}
