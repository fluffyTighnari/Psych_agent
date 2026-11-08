import type { GraphData, GraphNode } from '@/core/api/types'
import { ForceSimulation, type SimNode } from './physics'
import { SvgRenderer } from './svg-renderer'
import type { RenderState, Viewport } from './svg-renderer'

/**
 * 图谱引擎：生命周期、状态机、对外 API。
 *
 * **自动停帧是这个模块最重要的职责。**
 * 旧版 app.js 的 loop() 自 start() 后永不停机 —— 视图切走后仍在跑 RAF，
 * 持续耗电且拖慢整机。这里用「总位移低于阈值持续 N 帧」判定静止并停机，
 * 任何交互（拖拽/hover/缩放/数据变更/resize）都会唤醒。
 */

export interface GraphEngineOptions {
  /** 承载 SVG 的容器元素（不是 canvas） */
  host: HTMLElement
  onNodeClick?: (node: GraphNode) => void
  onNodeHover?: (node: GraphNode | null, evt: PointerEvent | null) => void
  onViewportChange?: (scale: number) => void
}

/** 低于此位移视为静止（px/帧） */
const STILL_THRESHOLD = 0.35
/** 连续静止帧数达此值则停帧（约 0.33s @60fps） */
const STILL_FRAMES_MAX = 20
const MIN_SCALE = 0.4
const MAX_SCALE = 3

export class GraphEngine {
  private sim = new ForceSimulation()
  private renderer: SvgRenderer
  private state: RenderState = {
    hoveredId: null,
    focusId: null,
    showLabels: true,
    adjacency: new Map(),
    filterType: 'all',
  }
  private view: Viewport = { scale: 1, offsetX: 0, offsetY: 0 }

  private raf: number | null = null
  private running = false
  private stillFrames = 0

  private dragging: SimNode | null = null
  private panning = false
  private panStart = { x: 0, y: 0, ox: 0, oy: 0 }
  private pointerStart = { x: 0, y: 0 }
  private movedSinceDown = false

  private resizeObserver: ResizeObserver | null = null
  private reducedMotion = false
  private motionQuery: MediaQueryList | null = null

  private rawData: GraphData = { nodes: [], links: [] }

  constructor(private opts: GraphEngineOptions) {
    this.renderer = new SvgRenderer(opts.host)
    this.motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    this.reducedMotion = this.motionQuery.matches

    // 运行时切换系统「减弱动效」设置也要生效，不必刷新页面
    this.motionQuery.addEventListener('change', this.onMotionPreferenceChange)

    this.bindEvents()
    this.observeResize()
  }

  private onMotionPreferenceChange = (e: MediaQueryListEvent): void => {
    this.reducedMotion = e.matches
    if (e.matches) {
      // 切到减弱：立刻把布局推到稳定态并停帧
      this.sim.settle(160)
      this.renderOnce()
      this.stop()
    }
  }

  /* ---------- 数据 ---------- */

  setData(data: GraphData): void {
    this.rawData = data
    const { width, height } = this.renderer.size
    this.sim.setData(data, width, height)
    this.state.adjacency = this.sim.adjacency()
    // 结构变更：按 id 增量增删 DOM（不重建，否则 CSS 过渡失效）
    this.renderer.setData(this.sim.nodes, this.sim.links)

    // 新节点：reduced-motion 下直接跳到稳定态，否则跑动画
    if (this.reducedMotion) {
      this.sim.settle(160)
      this.renderOnce()
    } else {
      this.wake()
    }
  }

  /* ---------- 尺寸 ---------- */

  resize(): void {
    const parent = this.opts.host
    const rect = parent.getBoundingClientRect()

    this.renderer.resize(rect.width, rect.height)
    this.sim.width = Math.max(rect.width, 1)
    this.sim.height = Math.max(rect.height, 1)

    // resize 后重新撒点是必要的（否则节点会挤在旧尺寸的坐标里）
    this.sim.setData(this.rawData, this.sim.width, this.sim.height)
    this.state.adjacency = this.sim.adjacency()
    this.renderer.setData(this.sim.nodes, this.sim.links)
    this.renderOnce()
    this.wake()
  }

  private observeResize(): void {
    const parent = this.opts.host
    if (!parent || typeof ResizeObserver === 'undefined') return
    this.resizeObserver = new ResizeObserver(() => {
      // 放在 rAF 里避免 ResizeObserver 循环警告
      requestAnimationFrame(() => this.resize())
    })
    this.resizeObserver.observe(parent)
  }

  /* ---------- 循环与停帧 ---------- */

  start(): void {
    if (this.running) return
    this.running = true
    this.stillFrames = 0
    this.loop()
  }

  stop(): void {
    this.running = false
    if (this.raf !== null) {
      cancelAnimationFrame(this.raf)
      this.raf = null
    }
  }

  /** 任何交互/变更都调用它：已停止则重启 */
  wake(): void {
    if (!this.running) this.start()
  }

  private loop = (): void => {
    if (!this.running) return

    const movement = this.sim.step()
    this.renderOnce()

    /*
     * 平均位移而非总位移：总位移会随节点数线性增长，
     * 6 个节点每个飘 0.06px 也超过阈值，导致永远停不下来。
     */
    const nodeCount = Math.max(this.sim.nodes.length, 1)
    const avgMovement = movement / nodeCount

    if (avgMovement < STILL_THRESHOLD) {
      if (++this.stillFrames > STILL_FRAMES_MAX) {
        // 稳定了：停帧，等下次交互唤醒
        this.stop()
        return
      }
    } else {
      this.stillFrames = 0
    }

    this.raf = requestAnimationFrame(this.loop)
  }

  private renderOnce(): void {
    this.renderer.draw(this.sim.nodes, this.sim.links, this.view, this.state)
  }

  /* ---------- 外部控制 ---------- */

  focusNode(id: string | null): void {
    this.state.focusId = id
    this.wake()
    this.renderOnce()
  }

  clearFocus(): void {
    this.focusNode(null)
  }

  setShowLabels(show: boolean): void {
    this.state.showLabels = show
    this.wake()
    this.renderOnce()
  }

  /** 聚焦模式：只显示某类节点（其余淡出到 0.12） */
  setFilter(type: GraphNode['type'] | 'all'): void {
    this.state.filterType = type
    this.wake()
    this.renderOnce()
  }

  zoomToFit(): void {
    const nodes = this.sim.nodes
    if (!nodes.length) return

    const { width, height } = this.renderer.size
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const n of nodes) {
      minX = Math.min(minX, n.x - n.r)
      maxX = Math.max(maxX, n.x + n.r)
      minY = Math.min(minY, n.y - n.r)
      maxY = Math.max(maxY, n.y + n.r)
    }

    const w = Math.max(maxX - minX, 1)
    const h = Math.max(maxY - minY, 1)
    const padding = 48
    const scale = Math.min(
      (width - padding * 2) / w,
      (height - padding * 2) / h,
      MAX_SCALE,
    )

    const clamped = Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale))
    this.view.scale = clamped
    this.view.offsetX = width / 2 - ((minX + maxX) / 2) * clamped
    this.view.offsetY = height / 2 - ((minY + maxY) / 2) * clamped

    this.opts.onViewportChange?.(clamped)
    this.wake()
    this.renderOnce()
  }

  zoomBy(factor: number, centerX?: number, centerY?: number): void {
    const { width, height } = this.renderer.size
    const cx = centerX ?? width / 2
    const cy = centerY ?? height / 2

    const next = Math.max(MIN_SCALE, Math.min(MAX_SCALE, this.view.scale * factor))
    const ratio = next / this.view.scale

    // 以光标为焦点缩放：偏移量同步调整
    this.view.offsetX = cx - (cx - this.view.offsetX) * ratio
    this.view.offsetY = cy - (cy - this.view.offsetY) * ratio
    this.view.scale = next

    this.opts.onViewportChange?.(next)
    this.wake()
    this.renderOnce()
  }

  resetView(): void {
    this.view = { scale: 1, offsetX: 0, offsetY: 0 }
    this.opts.onViewportChange?.(1)
    this.wake()
    this.renderOnce()
  }

  relayout(): void {
    this.sim.setData(this.rawData, this.sim.width, this.sim.height)
    for (const n of this.sim.nodes) n.appear = 0
    this.state.adjacency = this.sim.adjacency()
    this.renderer.setData(this.sim.nodes, this.sim.links)
    this.wake()
  }

  destroy(): void {
    this.stop()
    this.motionQuery?.removeEventListener('change', this.onMotionPreferenceChange)
    this.motionQuery = null
    this.resizeObserver?.disconnect()
    this.resizeObserver = null
    this.unbindEvents()
    this.renderer.destroy()
  }

  /* ---------- 交互 ---------- */

  private getPointer(e: PointerEvent): { x: number; y: number } {
    const rect = this.opts.host.getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  private hitTest(screenX: number, screenY: number): SimNode | null {
    const w = this.renderer.toWorld(screenX, screenY, this.view)
    return this.sim.findNode(w.x, w.y)
  }

  private toRaw(n: SimNode): GraphNode {
    return { id: n.id, name: n.name, type: n.type, summary: n.summary, source: n.source }
  }

  private onPointerDown = (e: PointerEvent): void => {
    // 只响应主键；同时阻止 SVG 标签进入原生文本选择，
    // 否则选择会话会抢走后续 pointermove / pointerup。
    if (e.button !== 0) return
    e.preventDefault()

    const p = this.getPointer(e)
    this.pointerStart = p
    this.movedSinceDown = false

    const hit = this.hitTest(p.x, p.y)
    if (hit) {
      this.dragging = hit
      hit.fx = hit.x
      hit.fy = hit.y
      this.opts.host.setPointerCapture(e.pointerId)
    } else {
      this.panning = true
      this.panStart = { x: p.x, y: p.y, ox: this.view.offsetX, oy: this.view.offsetY }
      this.opts.host.setPointerCapture(e.pointerId)
    }
    this.wake()
  }

  private onPointerMove = (e: PointerEvent): void => {
    const p = this.getPointer(e)

    if (this.dragging) {
      const w = this.renderer.toWorld(p.x, p.y, this.view)
      this.dragging.fx = w.x
      this.dragging.fy = w.y
      this.movedSinceDown = true
      this.wake()
      return
    }

    if (this.panning) {
      this.view.offsetX = this.panStart.ox + (p.x - this.panStart.x)
      this.view.offsetY = this.panStart.oy + (p.y - this.panStart.y)
      if (Math.hypot(p.x - this.pointerStart.x, p.y - this.pointerStart.y) > 3) {
        this.movedSinceDown = true
      }
      this.wake()
      return
    }

    // hover
    const hit = this.hitTest(p.x, p.y)
    const id = hit?.id ?? null
    if (id !== this.state.hoveredId) {
      this.state.hoveredId = id
      this.opts.host.style.cursor = hit ? 'pointer' : 'grab'
      this.opts.onNodeHover?.(hit ? this.toRaw(hit) : null, e)
      this.wake()
      this.renderOnce()
    } else if (hit) {
      // 位置变化时更新 tooltip
      this.opts.onNodeHover?.(this.toRaw(hit), e)
    }
  }

  private onPointerUp = (e: PointerEvent): void => {
    if (this.dragging) {
      this.dragging.fx = null
      this.dragging.fy = null
      this.dragging = null
    }
    this.panning = false
    try {
      this.opts.host.releasePointerCapture(e.pointerId)
    } catch {
      // 指针已释放，忽略
    }
  }

  private onClick = (e: MouseEvent): void => {
    // 拖拽/平移结束后的 click 不算点击
    if (this.movedSinceDown) return
    const rect = this.opts.host.getBoundingClientRect()
    const hit = this.hitTest(e.clientX - rect.left, e.clientY - rect.top)
    if (hit) this.opts.onNodeClick?.(this.toRaw(hit))
  }

  /*
   * 滚轮缩放：按 scroll 幅度连续缩放，而不是「一档跳到 min/max」。
   *
   * 旧实现每帧固定 ×1.12，但触控板/鼠标滚轮一次事件可能带很大的 deltaY，
   * 叠加后一次滚动就冲到边界。现在：
   *   - 用 deltaY 的自然对数做比例，幅度平滑；
   *   - 单次事件夹在 0.9–1.1，避免大 delta 一步跨完整个范围；
   *   - 配合 zoomTarget 的补间（见 tick），视觉上是连续推拉。
   */
  private onWheel = (e: WheelEvent): void => {
    e.preventDefault()
    const rect = this.opts.host.getBoundingClientRect()

    // 归一化：不同设备 deltaY 量级差异很大（行模式 vs 像素模式）
    const delta = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY
    // 平滑比例：|-100| 约对应 1.1 倍
    let factor = Math.exp(-delta * 0.0012)
    factor = Math.min(1.1, Math.max(0.9, factor))

    const next = Math.max(MIN_SCALE, Math.min(MAX_SCALE, this.view.scale * factor))
    const ratio = next / this.view.scale

    const cx = e.clientX - rect.left
    const cy = e.clientY - rect.top
    this.view.offsetX = cx - (cx - this.view.offsetX) * ratio
    this.view.offsetY = cy - (cy - this.view.offsetY) * ratio
    this.view.scale = next

    this.opts.onViewportChange?.(next)
    this.wake()
    this.renderOnce()
  }

  private onDblClick = (): void => {
    this.zoomToFit()
  }

  private onLeave = (): void => {
    if (this.state.hoveredId) {
      this.state.hoveredId = null
      this.opts.onNodeHover?.(null, null)
      this.renderOnce()
    }
  }

  private bindEvents(): void {
    const c = this.opts.host
    c.addEventListener('pointerdown', this.onPointerDown)
    c.addEventListener('pointermove', this.onPointerMove)
    c.addEventListener('pointerup', this.onPointerUp)
    c.addEventListener('pointercancel', this.onPointerUp)
    c.addEventListener('pointerleave', this.onLeave)
    c.addEventListener('click', this.onClick)
    c.addEventListener('wheel', this.onWheel, { passive: false })
    c.addEventListener('dblclick', this.onDblClick)
    c.style.touchAction = 'none'
  }

  private unbindEvents(): void {
    const c = this.opts.host
    c.removeEventListener('pointerdown', this.onPointerDown)
    c.removeEventListener('pointermove', this.onPointerMove)
    c.removeEventListener('pointerup', this.onPointerUp)
    c.removeEventListener('pointercancel', this.onPointerUp)
    c.removeEventListener('pointerleave', this.onLeave)
    c.removeEventListener('click', this.onClick)
    c.removeEventListener('wheel', this.onWheel)
    c.removeEventListener('dblclick', this.onDblClick)
  }

  /* ---------- 查询 ---------- */

  get nodes(): SimNode[] {
    return this.sim.nodes
  }

  get scale(): number {
    return this.view.scale
  }
}
