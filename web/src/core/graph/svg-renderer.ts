import type { SimLink, SimNode } from './physics'
import { glyphFor, GLYPH_LABEL, type GlyphType } from './glyphs'

/**
 * SVG 渲染层：增量更新，不做 DOM 重建。
 *
 * 为什么必须增量：每帧 `innerHTML = ''` 会摧毁 CSS 过渡 —— 元素被替换后
 * 过渡没有起点，所有 hover/选中动画都会失效。所以：
 *   - setData 时按 id diff，只增删改必要的元素
 *   - 每帧只改 <g> 的 transform 属性（几何不变，浏览器可 GPU 加速）
 *   - 状态（hover/选中/淡出）走 CSS 类，不碰属性
 *
 * 连线用**单条 <path>** 承载全部线段（含 moveTo/lineTo 序列），
 * 30 条边只有 1 个 DOM 节点，避免几十个独立元素拖慢样式计算。
 */

export interface Viewport {
  scale: number
  offsetX: number
  offsetY: number
}

export interface RenderState {
  hoveredId: string | null
  focusId: string | null
  showLabels: boolean
  adjacency: Map<string, Set<string>>
  filterType: GlyphType | 'all'
}

const SVG_NS = 'http://www.w3.org/2000/svg'

/** 标签最长字符数（超出截断） */
const LABEL_MAX_LEN = 12
/** 度数达到此值的文档才常驻标签 */
const DOC_LABEL_MIN_DEGREE = 3
const MEM_LABEL_MIN_DEGREE = 2

interface NodeEls {
  group: SVGGElement
  label: SVGTextElement
  /** 上一次的可见性状态，避免每帧写类 */
  lastClass: string
}

export class SvgRenderer {
  private root: SVGSVGElement
  private viewportG: SVGGElement
  private linkPath: SVGPathElement
  private linkPathDashed: SVGPathElement
  private nodeLayer: SVGGElement
  private labelLayer: SVGGElement

  private nodeEls = new Map<string, NodeEls>()
  private width = 0
  private height = 0
  /** 当前 viewScale，用于标签与描边的反向补偿 */
  private viewScale = 1

  constructor(host: HTMLElement) {
    this.root = document.createElementNS(SVG_NS, 'svg')
    this.root.classList.add('graph-svg')
    this.root.setAttribute('role', 'group')
    this.root.setAttribute('aria-label', '会话关联图谱画布')

    // 视口变换层：平移缩放只改这一个 transform
    this.viewportG = document.createElementNS(SVG_NS, 'g')
    this.viewportG.classList.add('graph-svg__viewport')

    // 连线层（在节点之下）
    const linkLayer = document.createElementNS(SVG_NS, 'g')
    linkLayer.classList.add('graph-svg__links')
    this.linkPath = document.createElementNS(SVG_NS, 'path')
    this.linkPath.classList.add('glink', 'glink--solid')
    this.linkPathDashed = document.createElementNS(SVG_NS, 'path')
    this.linkPathDashed.classList.add('glink', 'glink--dashed')
    linkLayer.append(this.linkPath, this.linkPathDashed)

    this.nodeLayer = document.createElementNS(SVG_NS, 'g')
    this.nodeLayer.classList.add('graph-svg__nodes')
    this.labelLayer = document.createElementNS(SVG_NS, 'g')
    this.labelLayer.classList.add('graph-svg__labels')

    this.viewportG.append(linkLayer, this.nodeLayer, this.labelLayer)
    this.root.append(this.buildDefs(), this.viewportG)
    host.appendChild(this.root)
  }

  /**
   * SVG <defs>：光晕的径向渐变遮罩。
   *
   * 光晕圆用 `fill: currentColor`（CSS 控制颜色，暗色模式免重绘），
   * 再由这层遮罩把中心挖空、边缘做柔和衰减 —— 只在外圈留下一道光，不糊住字形。
   *
   * 为什么用遮罩而不是渐变填充：
   * 早先写成 `fill="url(#gnode-halo-grad)"` + `<radialGradient>`，但 CSS 里的
   * `fill: currentColor` 会覆盖 SVG 表现属性（presentation attribute 优先级最低），
   * 渐变成了死代码，光晕一直是一块实心圆。遮罩走的是独立属性，不会被 fill 规则顶掉。
   * 遮罩用 luminance 之外的默认 alpha 通道，圆心 alpha=0 → 中心完全透明。
   */
  private buildDefs(): SVGDefsElement {
    const defs = document.createElementNS(SVG_NS, 'defs')

    const mask = document.createElementNS(SVG_NS, 'radialGradient')
    mask.setAttribute('id', 'gnode-halo-mask-grad')
    mask.setAttribute('cx', '50%')
    mask.setAttribute('cy', '50%')
    mask.setAttribute('r', '50%')

    // 中心全透明，到 82% 处最亮，边缘再收回 0 —— 一圈柔光
    const stops: [string, string][] = [
      ['0%', '0'],
      ['62%', '0.1'],
      ['82%', '0.75'],
      ['100%', '0'],
    ]
    for (const [offset, opacity] of stops) {
      const stop = document.createElementNS(SVG_NS, 'stop')
      stop.setAttribute('offset', offset)
      stop.setAttribute('stop-color', '#fff')
      stop.setAttribute('stop-opacity', opacity)
      mask.appendChild(stop)
    }
    defs.appendChild(mask)

    const maskEl = document.createElementNS(SVG_NS, 'mask')
    maskEl.setAttribute('id', 'gnode-halo-mask')
    // maskContentUnits=objectBoundingBox 让遮罩坐标相对光晕圆本身，
    // 这样圆的大小变化时渐变自动适配，不用重算
    maskEl.setAttribute('maskUnits', 'objectBoundingBox')
    maskEl.setAttribute('maskContentUnits', 'objectBoundingBox')
    const maskCircle = document.createElementNS(SVG_NS, 'circle')
    maskCircle.setAttribute('cx', '0.5')
    maskCircle.setAttribute('cy', '0.5')
    maskCircle.setAttribute('r', '0.5')
    maskCircle.setAttribute('fill', 'url(#gnode-halo-mask-grad)')
    maskEl.appendChild(maskCircle)
    defs.appendChild(maskEl)

    return defs
  }

  /* ---------- 尺寸 ---------- */

  resize(width: number, height: number): void {
    this.width = Math.max(width, 1)
    this.height = Math.max(height, 1)
    this.root.setAttribute('width', String(this.width))
    this.root.setAttribute('height', String(this.height))
    this.root.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`)
    this.root.style.width = `${this.width}px`
    this.root.style.height = `${this.height}px`
  }

  get size(): { width: number; height: number } {
    return { width: this.width, height: this.height }
  }

  /* ---------- 数据：增量 diff ---------- */

  setData(nodes: SimNode[], links: SimLink[]): void {
    const alive = new Set<string>()

    for (const n of nodes) {
      alive.add(n.id)
      let els = this.nodeEls.get(n.id)
      if (!els) {
        els = this.createNode(n)
        this.nodeEls.set(n.id, els)
      } else {
        this.updateNodeMeta(els, n)
      }
      this.positionNode(els, n)
    }

    // 移除已不存在的
    for (const [id, els] of this.nodeEls) {
      if (alive.has(id)) continue
      els.group.remove()
      els.label.remove()
      this.nodeEls.delete(id)
    }

    this.buildLinks(links)
  }

  private createNode(n: SimNode): NodeEls {
    const glyph = glyphFor(n.type)
    const els: NodeEls = {
      group: document.createElementNS(SVG_NS, 'g'),
      label: document.createElementNS(SVG_NS, 'text'),
      lastClass: '',
    }

    const g = els.group
    g.classList.add('gnode', `gnode--${n.type}`)
    if (glyph.image) g.classList.add('gnode--image')
    /*
     * 无障碍：用 role="img" 而非 button。
     * 节点的点击由容器上的命中检测处理（不是 DOM 事件），
     * 若这里再声明 role="button"，会与外层 tabindex 容器形成
     * nested-interactive 违规。屏幕阅读器通过 <title> 获得完整描述。
     */
    g.setAttribute('role', 'img')
    g.dataset.nodeId = n.id

    const title = document.createElementNS(SVG_NS, 'title')
    title.textContent = this.nodeTitle(n)
    g.appendChild(title)

    /*
     * 字形坐标系：以节点中心为原点，单位 1 = 半径 r。
     * 所有几何元素（含光晕、选中环）都必须放在这个 scaleG 里，
     * 否则单位不一致 —— 曾把光晕写成绝对 px(r=1.9)，结果只有 1.9px。
     */
    const scaleG = document.createElementNS(SVG_NS, 'g')
    scaleG.classList.add('gnode__glyph')
    scaleG.setAttribute('transform', `scale(${n.r})`)

    /*
     * 光晕：实心圆 + 遮罩挖空中心。
     * 颜色走 CSS `fill: currentColor`（按节点类型取色、暗色模式免重绘），
     * 形状由 mask 决定 —— 若直接在这里写 fill="url(#...)"，会被 CSS 的 fill 规则顶掉。
     */
    const halo = document.createElementNS(SVG_NS, 'circle')
    halo.classList.add('gnode__halo')
    halo.setAttribute('cx', '0')
    halo.setAttribute('cy', '0')
    halo.setAttribute('r', '1.55')
    halo.setAttribute('mask', 'url(#gnode-halo-mask)')
    scaleG.appendChild(halo)

    /*
     * 48 × 48 设计坐标 → r 单位：
     *   scale(1/24) 把 48 格压到 2 格，translate(-24 -24) 把中心移到原点。
     * 这样 glyphs.ts 里的几何可以直接复制设计稿，不必逐点换算。
     */
    const glyphScale = document.createElementNS(SVG_NS, 'g')
    glyphScale.classList.add('gnode__glyph-space')
    glyphScale.setAttribute('transform', 'scale(0.0416667)')
    const glyphCoords = document.createElementNS(SVG_NS, 'g')
    glyphCoords.classList.add('gnode__glyph-coords')
    glyphCoords.setAttribute('transform', 'translate(-24 -24)')
    glyphScale.appendChild(glyphCoords)
    scaleG.appendChild(glyphScale)

    if (glyph.image) {
      const image = document.createElementNS(SVG_NS, 'image')
      image.classList.add('gnode__image')
      image.setAttribute('href', glyph.image.href)
      image.setAttribute('x', String(glyph.image.x))
      image.setAttribute('y', String(glyph.image.y))
      image.setAttribute('width', String(glyph.image.width))
      image.setAttribute('height', String(glyph.image.height))
      image.setAttribute('preserveAspectRatio', 'xMidYMid meet')
      glyphCoords.appendChild(image)
    } else {
      for (const part of glyph.parts) {
        const path = document.createElementNS(SVG_NS, 'path')
        path.classList.add('gnode__part', `gnode__part--${part.role}`)
        path.setAttribute('d', part.d)
        if (part.transform) path.setAttribute('transform', part.transform)
        glyphCoords.appendChild(path)
      }

      for (const dot of glyph.dots ?? []) {
        const c = document.createElementNS(SVG_NS, 'circle')
        c.classList.add('gnode__dot')
        c.setAttribute('cx', String(dot.cx))
        c.setAttribute('cy', String(dot.cy))
        c.setAttribute('r', String(dot.r))
        c.setAttribute('opacity', String(dot.opacity ?? 1))
        glyphCoords.appendChild(c)
      }
    }

    // 选中态外圈（r 单位，与字形同坐标系）
    const ring = document.createElementNS(SVG_NS, 'circle')
    ring.classList.add('gnode__ring')
    ring.setAttribute('cx', '0')
    ring.setAttribute('cy', '0')
    ring.setAttribute('r', '1.42')
    scaleG.appendChild(ring)

    g.appendChild(scaleG)

    // 标签
    els.label.classList.add('glabel', `glabel--${n.type}`)
    els.label.textContent =
      n.name.length > LABEL_MAX_LEN ? n.name.slice(0, LABEL_MAX_LEN) + '…' : n.name

    this.nodeLayer.appendChild(g)
    this.labelLayer.appendChild(els.label)
    return els
  }

  /** 节点名 / 摘要变化时更新（不重建元素） */
  private updateNodeMeta(els: NodeEls, n: SimNode): void {
    const title = els.group.querySelector('title')
    const next = this.nodeTitle(n)
    if (title && title.textContent !== next) title.textContent = next

    const labelText =
      n.name.length > LABEL_MAX_LEN ? n.name.slice(0, LABEL_MAX_LEN) + '…' : n.name
    if (els.label.textContent !== labelText) els.label.textContent = labelText
  }

  private nodeTitle(n: SimNode): string {
    const kind = GLYPH_LABEL[n.type] ?? n.type
    return n.summary ? `${kind}：${n.name}\n${n.summary}` : `${kind}：${n.name}`
  }

  /** 每帧只更新位置与缩放 */
  private positionNode(els: NodeEls, n: SimNode): void {
    const appear = 0.6 + 0.4 * n.appear
    els.group.setAttribute(
      'transform',
      `translate(${n.x.toFixed(2)} ${n.y.toFixed(2)}) scale(${appear.toFixed(3)})`,
    )
    // 标签反向缩放，保证任何倍率下字号恒定可读
    const labelScale = this.labelScale()
    els.label.setAttribute(
      'transform',
      `translate(${n.x.toFixed(2)} ${(n.y + n.r + 12).toFixed(2)}) scale(${labelScale.toFixed(3)})`,
    )
  }

  /**
   * 描边反向补偿：放大 3x 时线条只增粗到约 1.64x，缩小到 0.4x 时只减细到 0.66x。
   * 指数 0.45 是折中 —— 完全固定会让大倍率下线太细，完全线性又粗成马克笔。
   */
  private strokeScale(): number {
    const s = 1 / Math.pow(this.viewScale, 0.45)
    return Math.min(1.5, Math.max(0.7, s))
  }

  private labelScale(): number {
    const s = 1 / this.viewScale
    return Math.min(1.6, Math.max(0.6, s))
  }

  /** 全部连线合成两条 path（实线 / 虚线各一条） */
  private buildLinks(links: SimLink[]): void {
    let solid = ''
    const dashed = ''

    for (const l of links) {
      const a = l.source
      const b = l.target
      const mx = (a.x + b.x) / 2
      const my = (a.y + b.y) / 2
      const dx = b.x - a.x
      const dy = b.y - a.y
      const dist = Math.hypot(dx, dy) || 1
      const curve = Math.min(dist * 0.12, 40)
      // 用两端 id 字典序决定偏转方向，保证同一条边方向稳定
      const sign = a.id < b.id ? 1 : -1
      const cx = mx + (-dy / dist) * curve * sign
      const cy = my + (dx / dist) * curve * sign

      const seg = `M ${a.x.toFixed(2)} ${a.y.toFixed(2)} Q ${cx.toFixed(2)} ${cy.toFixed(2)} ${b.x.toFixed(2)} ${b.y.toFixed(2)}`
      solid += seg
    }

    this.linkPath.setAttribute('d', solid.trim())
    this.linkPathDashed.setAttribute('d', dashed)
  }

  /* ---------- 每帧 ---------- */

  /**
   * 每帧渲染：只更新位置与状态类。
   * 连线几何随节点移动而变，因此也要重算 —— 但仍是**同一个 path 元素**，
   * 只改 d 属性，不产生 DOM 增删。
   */
  draw(nodes: SimNode[], links: SimLink[], view: Viewport, state: RenderState): void {
    this.viewScale = view.scale

    this.viewportG.setAttribute(
      'transform',
      `translate(${view.offsetX} ${view.offsetY}) scale(${view.scale})`,
    )

    /*
     * 描边补偿：直接下发像素值，不走 calc。
     * 放大 3x 时线条只增粗到约 1.64x（而非 3x），缩小到 0.4x 时只减细到 0.66x。
     * 完全固定会让大倍率下线太细，完全线性又粗成马克笔。
     */
    const ss = this.strokeScale()
    this.root.style.setProperty('--sw-main', `${(1.5 * ss).toFixed(2)}px`)
    this.root.style.setProperty('--sw-trunk', `${(1.9 * ss).toFixed(2)}px`)
    this.root.style.setProperty('--sw-sub', `${(1.1 * ss).toFixed(2)}px`)
    this.root.style.setProperty('--sw-thin', `${(0.9 * ss).toFixed(2)}px`)
    this.root.style.setProperty('--sw-trail', `${(1.3 * ss).toFixed(2)}px`)
    this.root.style.setProperty('--sw-link', `${(1.2 * ss).toFixed(2)}px`)
    this.root.style.setProperty('--sw-focus', `${(2 * ss).toFixed(2)}px`)

    const activeId = state.hoveredId ?? state.focusId
    const neighbors = activeId ? state.adjacency.get(activeId) ?? new Set<string>() : null

    for (const n of nodes) {
      const els = this.nodeEls.get(n.id)
      if (!els) continue
      this.positionNode(els, n)

      // 状态类：只在变化时写，避免每帧触发样式重算
      let cls = `gnode gnode--${n.type}`
      if (glyphFor(n.type).image) cls += ' gnode--image'
      if (n.id === state.hoveredId) cls += ' is-hovered'
      if (n.id === state.focusId) cls += ' is-active'
      if (state.filterType !== 'all' && n.type !== state.filterType) cls += ' is-dimmed'
      else if (activeId && n.id !== activeId && !neighbors?.has(n.id)) cls += ' is-dimmed'

      if (cls !== els.lastClass) {
        els.group.setAttribute('class', cls)
        els.lastClass = cls
      }

      // 标签可见性
      const visible = this.shouldLabel(n, nodes.length, state, activeId, neighbors)
      els.label.classList.toggle('is-hidden', !visible)
    }

    this.buildLinks(links)
  }

  private shouldLabel(
    n: SimNode,
    total: number,
    state: RenderState,
    activeId: string | null,
    neighbors: Set<string> | null,
  ): boolean {
    if (!state.showLabels || !n.name) return false

    // 被淡出的节点不显示标签
    if (state.filterType !== 'all' && n.type !== state.filterType) return false
    if (activeId && n.id !== activeId && !neighbors?.has(n.id)) return false

    // 节点少时全显示；否则按类型与度数分级
    if (total <= 24) return true
    if (n.type === 'session' || n.type === 'reason') return true
    if (n.id === state.hoveredId || n.id === state.focusId) return true
    if (n.type === 'document') return n.degree >= DOC_LABEL_MIN_DEGREE
    if (n.type === 'memory') return n.degree >= MEM_LABEL_MIN_DEGREE
    return false
  }

  /** 屏幕坐标 → 世界坐标（交互命中检测用，与 Canvas 版逻辑一致） */
  toWorld(screenX: number, screenY: number, view: Viewport): { x: number; y: number } {
    return {
      x: (screenX - view.offsetX) / view.scale,
      y: (screenY - view.offsetY) / view.scale,
    }
  }

  destroy(): void {
    this.root.remove()
    this.nodeEls.clear()
  }
}
