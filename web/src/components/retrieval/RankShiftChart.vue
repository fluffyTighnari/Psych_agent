<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppEmpty from '@/components/ui/AppEmpty.vue'
import {
  buildRankShiftModel,
  pointAt,
  trackSummary,
  type RankShiftModel,
  type RankTrack,
} from '@/core/retrieval/rank-shift'
import type { RetrievalDebugResp } from '@/core/api/types'

/**
 * 排名迁移图（Canvas 斜率图）。
 *
 * 一张图回答「重排到底有没有用」：
 * 同一文档在 dense → bm25 → rrf → rerank 各阶段的位次流动，
 * 进入最终的用朱红、被淘汰的用灰、后期召回的起点标 +。
 *
 * 用 Canvas 而非 SVG/DOM 的理由：轨迹数可达数十条、需要 hover 高亮整条路径、
 * 且要随容器自适应——Canvas 单层重绘比维护几十个 SVG path 更直接。
 */

const props = defineProps<{
  data: RetrievalDebugResp | null
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const wrapRef = ref<HTMLElement | null>(null)
const hoveredId = ref<string | null>(null)

const model = computed<RankShiftModel | null>(() =>
  props.data ? buildRankShiftModel(props.data) : null,
)

/* ---------- 绘制参数 ---------- */

const PAD = { top: 34, right: 120, bottom: 26, left: 46 }
const ROW_H = 24
const MIN_H = 180

let raf = 0
let dpr = 1
let w = 0
let h = 0
/** 右侧留白，按标题实际宽度动态计算（见 draw） */
let rightPad = PAD.right

/** 每列内部各 track 的 y 坐标（考虑真实位次，不做槽位压缩） */
function yFor(rank: number): number {
  const innerH = h - PAD.top - PAD.bottom
  const maxR = Math.max(model.value?.maxRank ?? 0, 1)
  // 位次 0 在最上
  return PAD.top + (rank / Math.max(maxR, 1)) * Math.min(innerH, maxR * ROW_H)
}

function xFor(col: number): number {
  const cols = model.value?.columns.length ?? 1
  if (cols <= 1) return PAD.left
  const innerW = w - PAD.left - rightPad
  return PAD.left + (col / (cols - 1)) * innerW
}

function readColors() {
  const cs = getComputedStyle(document.documentElement)
  const v = (n: string, fb: string) => cs.getPropertyValue(n).trim() || fb
  return {
    accent: v('--accent', '#c24a2e'),
    accentDeep: v('--accent-deep', '#a03820'),
    document: v('--entity-document', '#4e6d6a'),
    disabled: v('--text-disabled', '#a89a86'),
    text: v('--text-primary', '#2a231c'),
    tertiary: v('--text-tertiary', '#746750'),
    border: v('--border', '#ddd2bd'),
    surface: 'rgba(253, 251, 245, 0.94)',
    surfaceRaised: v('--surface-raised', '#faf6ec'),
    fontSans: v('--font-sans', 'sans-serif'),
    fontMono: v('--font-mono', 'monospace'),
  }
}

function colorFor(t: RankTrack, colors: ReturnType<typeof readColors>): string {
  if (t.status === 'final') return colors.accent
  if (t.status === 'appeared') return colors.document
  return colors.disabled
}

function draw() {
  const canvas = canvasRef.value
  const wrap = wrapRef.value ?? canvas?.parentElement
  if (!canvas || !wrap || !model.value) return

  const m = model.value
  const colors = readColors()

  dpr = window.devicePixelRatio || 1
  const rect = wrap.getBoundingClientRect()

  w = Math.max(rect.width, 240)
  // 高度按位次深度决定，保证不挤
  const desiredH = PAD.top + PAD.bottom + Math.max(m.maxRank * ROW_H, MIN_H - PAD.top - PAD.bottom)
  h = Math.max(desiredH, MIN_H)

  canvas.width = w * dpr
  canvas.height = h * dpr
  canvas.style.width = `${w}px`
  canvas.style.height = `${h}px`

  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)

  /*
   * 右侧留白按「最长标题的实际像素宽度」动态计算。
   * 固定 120px 装不下中文标题（13 字可达 ~150px），会把标注裁掉。
   */
  ctx.font = `400 10.5px ${colors.fontSans}`
  const measured = m.tracks.map((t) => {
    const label = t.title.length > 13 ? t.title.slice(0, 13) + '…' : t.title
    return ctx.measureText(label).width
  })
  const maxLabelW = measured.length ? Math.max(...measured) : 0
  rightPad = Math.min(Math.max(96, maxLabelW + 22), Math.max(96, w * 0.34))

  /* ---- 列头与竖线 ---- */
  m.columns.forEach((col, i) => {
    const x = xFor(i)

    ctx.strokeStyle = colors.border
    ctx.lineWidth = 1
    ctx.setLineDash([2, 3])
    ctx.beginPath()
    ctx.moveTo(x, PAD.top - 12)
    ctx.lineTo(x, h - PAD.bottom)
    ctx.stroke()
    ctx.setLineDash([])

    // 列名
    ctx.font = `500 11px ${colors.fontSans}`
    ctx.textAlign = 'center'
    ctx.fillStyle = colors.tertiary
    ctx.fillText(col.label, x, PAD.top - 18)

    // 候选数
    ctx.font = `400 9.5px ${colors.fontMono}`
    ctx.fillStyle = colors.disabled
    ctx.fillText(String(col.count), x, PAD.top - 5)
  })

  /* ---- 轨迹 ---- */
  const sorted = m.tracks
  // 先画非高亮的，再画高亮的，保证高亮在最上层
  const drawTrack = (t: RankTrack) => {
    const color = colorFor(t, colors)
    const isHovered = hoveredId.value === t.docId
    const dim = hoveredId.value !== null && !isHovered

    ctx.globalAlpha = dim ? 0.14 : 1
    ctx.strokeStyle = color
    ctx.lineWidth = isHovered ? 2.6 : 1.6

    const pts = t.points.map((p) => ({ x: xFor(p.column), y: yFor(p.rank), p }))

    // 折线：贝塞尔让转折更柔和，视觉上更像「流动」而非折线图
    if (pts.length > 1) {
      ctx.beginPath()
      ctx.moveTo(pts[0]!.x, pts[0]!.y)
      for (let i = 1; i < pts.length; i++) {
        const prev = pts[i - 1]!
        const cur = pts[i]!
        const midX = (prev.x + cur.x) / 2
        ctx.bezierCurveTo(midX, prev.y, midX, cur.y, cur.x, cur.y)
      }
      ctx.stroke()
    }

    // 端点
    for (const pt of pts) {
      const r = isHovered ? 4 : 3
      // 新召回的起点画成空心 + 加号
      const isFirst = pt === pts[0]
      if (isFirst && t.firstColumn > 0) {
        ctx.beginPath()
        ctx.arc(pt.x, pt.y, r + 1, 0, Math.PI * 2)
        ctx.fillStyle = colors.surfaceRaised
        ctx.fill()
        ctx.strokeStyle = color
        ctx.lineWidth = 1.4
        ctx.stroke()

        ctx.beginPath()
        ctx.moveTo(pt.x - 2, pt.y)
        ctx.lineTo(pt.x + 2, pt.y)
        ctx.moveTo(pt.x, pt.y - 2)
        ctx.lineTo(pt.x, pt.y + 2)
        ctx.lineWidth = 1
        ctx.stroke()
      } else {
        ctx.beginPath()
        ctx.arc(pt.x, pt.y, r, 0, Math.PI * 2)
        ctx.fillStyle = color
        ctx.fill()
      }
    }

    // 最终结果右侧标注标题
    const finalPt = pointAt(t, m.columns.length - 1)
    if (finalPt) {
      ctx.globalAlpha = dim ? 0.2 : 1
      ctx.font = `${isHovered ? 600 : 400} 10.5px ${colors.fontSans}`
      ctx.textAlign = 'left'
      ctx.fillStyle = isHovered ? colors.accentDeep : colors.text

      const label = t.title.length > 13 ? t.title.slice(0, 13) + '…' : t.title
      const labelX = xFor(m.columns.length - 1) + 10
      const labelY = yFor(finalPt.rank) + 3.5

      // 描边底：压在其它轨迹上仍可读
      ctx.lineWidth = 3
      ctx.strokeStyle = colors.surface
      ctx.strokeText(label, labelX, labelY)
      ctx.fillText(label, labelX, labelY)
    }

    ctx.globalAlpha = 1
  }

  for (const t of sorted) if (t.docId !== hoveredId.value) drawTrack(t)
  const hovered = sorted.find((t) => t.docId === hoveredId.value)
  if (hovered) drawTrack(hovered)
}

function scheduleDraw() {
  cancelAnimationFrame(raf)
  raf = requestAnimationFrame(draw)
}

/* ---------- 命中检测 ---------- */

function hitTest(px: number, py: number): RankTrack | null {
  const m = model.value
  if (!m) return null

  let best: { d: number; track: RankTrack } | null = null

  for (const t of m.tracks) {
    for (const p of t.points) {
      const x = xFor(p.column)
      const y = yFor(p.rank)
      const d = Math.hypot(px - x, py - y)
      if (d < 12 && (!best || d < best.d)) best = { d, track: t }
    }
  }
  return best?.track ?? null
}

function onMouseMove(e: MouseEvent) {
  const canvas = canvasRef.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const hit = hitTest(e.clientX - rect.left, e.clientY - rect.top)
  const next = hit?.docId ?? null
  if (next !== hoveredId.value) {
    hoveredId.value = next
    canvas.style.cursor = hit ? 'pointer' : 'default'
    scheduleDraw()
  }
}

function onMouseLeave() {
  if (hoveredId.value) {
    hoveredId.value = null
    scheduleDraw()
  }
}

/* ---------- 生命周期 ---------- */

let ro: ResizeObserver | null = null

onMounted(() => {
  scheduleDraw()
  if (wrapRef.value && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => scheduleDraw())
    ro.observe(wrapRef.value)
  }
})

onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  ro?.disconnect()
})

watch(() => props.data, () => scheduleDraw(), { deep: false })

/* ---------- 等价表格（无障碍） ---------- */

const rows = computed(() => model.value?.tracks ?? [])
</script>

<template>
  <div class="rs">
    <AppEmpty
      v-if="!model || !rows.length"
      icon="filter"
      title="暂无排名数据"
      desc="运行一次检索后，这里会显示同一文档在各阶段的位次流动"
    />

    <template v-else>
      <div ref="wrapRef" class="rs__canvas-wrap">
        <canvas
          ref="canvasRef"
          class="rs__canvas"
          role="img"
          :aria-label="`排名迁移图：${rows.length} 篇文档跨 ${model.columns.length} 个阶段的位次变化，其中 ${model.finalCount} 篇进入最终结果`"
          @mousemove="onMouseMove"
          @mouseleave="onMouseLeave"
        ></canvas>
      </div>

      <div class="rs__legend">
        <span class="rs__legend-item">
          <i class="rs__line rs__line--final"></i>进入最终
        </span>
        <span class="rs__legend-item">
          <i class="rs__line rs__line--appeared"></i>后期召回
        </span>
        <span class="rs__legend-item">
          <i class="rs__line rs__line--dropped"></i>被淘汰
        </span>
        <span class="rs__legend-item rs__legend-item--hint">
          圆点 = 该阶段位次 · + = 新召回起点
        </span>
      </div>

      <details class="rs__table-toggle">
        <summary>以表格查看（{{ rows.length }} 条轨迹）</summary>
        <table class="rs__table">
          <thead>
            <tr>
              <th>文档</th>
              <th v-for="c in model.columns" :key="c.key">{{ c.label }}</th>
              <th>结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in rows" :key="t.docId">
              <td class="rs__doc" :title="t.title">{{ t.title }}</td>
              <td v-for="(c, i) in model.columns" :key="c.key" class="rs__rank tabular">
                <template v-if="pointAt(t, i)">#{{ (pointAt(t, i)?.rank ?? 0) + 1 }}</template>
                <span v-else class="rs__dash">—</span>
              </td>
              <td>
                <span class="rs__status" :class="`rs__status--${t.status}`">
                  {{ t.status === 'final' ? '最终' : t.status === 'appeared' ? '后期召回' : '淘汰' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </details>

      <!-- 屏幕阅读器的纯文本等价内容 -->
      <p class="sr-only">
        <span v-for="t in rows" :key="t.docId">{{ trackSummary(t) }}；</span>
      </p>
    </template>
  </div>
</template>

<style scoped>
.rs {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.rs__canvas-wrap {
  width: 100%;
  min-width: 0;
}

.rs__canvas {
  display: block;
  width: 100%;
}

/* ---------- 图例 ---------- */
.rs__legend {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  flex-wrap: wrap;
  font-size: var(--fs-2xs);
  color: var(--text-secondary);
}

.rs__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.rs__legend-item--hint {
  margin-left: auto;
  color: var(--text-tertiary);
}

.rs__line {
  display: inline-block;
  width: 16px;
  height: 2px;
  border-radius: 1px;
}

.rs__line--final {
  background: var(--accent);
}

.rs__line--appeared {
  background: var(--entity-document);
}

.rs__line--dropped {
  background: var(--text-disabled);
}

/* ---------- 等价表格 ---------- */
.rs__table-toggle {
  font-size: var(--fs-2xs);
}

.rs__table-toggle summary {
  cursor: pointer;
  color: var(--text-tertiary);
  padding: 3px 0;
}

.rs__table-toggle summary:hover {
  color: var(--text-secondary);
}

.rs__table {
  width: 100%;
  margin-top: var(--sp-1);
  border-collapse: collapse;
  font-size: var(--fs-2xs);
}

.rs__table th {
  text-align: left;
  padding: 3px 6px;
  font-weight: var(--fw-medium);
  color: var(--text-tertiary);
  border-bottom: 1px solid var(--border-soft);
  white-space: nowrap;
}

.rs__table td {
  padding: 3px 6px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-soft);
}

.rs__doc {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rs__rank {
  font-family: var(--font-mono);
  white-space: nowrap;
}

.rs__dash {
  color: var(--text-disabled);
}

.rs__status {
  padding: 1px 6px;
  border-radius: var(--r-pill);
  white-space: nowrap;
}

.rs__status--final {
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
}

.rs__status--appeared {
  background: rgba(78, 109, 106, 0.12);
  color: #3f5a57;
}

.rs__status--dropped {
  background: var(--surface-sunken);
  color: var(--text-tertiary);
}
</style>
