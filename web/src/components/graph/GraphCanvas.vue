<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import NodeGlyph from '@/components/graph/NodeGlyph.vue'
import { GraphEngine } from '@/core/graph/engine'
import { useGraphStore } from '@/stores/graph'
import type { GraphNode } from '@/core/api/types'

/**
 * 图谱画布容器。
 *
 * 只做「挂载/卸载引擎」与「把 store 变化转成引擎调用」，
 * 所有渲染与物理都在 core/graph/ 的纯 TS 模块里，不依赖 Vue。
 */

const graph = useGraphStore()

const hostRef = ref<HTMLElement | null>(null)
const hovered = ref<GraphNode | null>(null)
const tooltip = ref({ x: 0, y: 0, visible: false })
const scale = ref(1)
const showLabels = ref(true)
const filterType = ref<GraphNode['type'] | 'all'>('all')

let engine: GraphEngine | null = null

function positionTooltip(evt: PointerEvent | null) {
  if (!evt) return
  const OFFSET = 16
  const TIP_W = 280
  const TIP_H = 96

  let x = evt.clientX + OFFSET
  let y = evt.clientY + OFFSET

  // 边界翻转：靠右/靠下时改为向左/向上展开，避免溢出视口
  if (x + TIP_W > window.innerWidth - 8) x = evt.clientX - TIP_W - OFFSET
  if (y + TIP_H > window.innerHeight - 8) y = evt.clientY - TIP_H - OFFSET

  tooltip.value = { x, y, visible: true }
}

onMounted(() => {
  const host = hostRef.value
  if (!host) return

  engine = new GraphEngine({
    host,
    onNodeClick: (node) => graph.select(node),
    onNodeHover: (node, evt) => {
      hovered.value = node
      if (node && evt) positionTooltip(evt)
      else tooltip.value.visible = false
    },
    onViewportChange: (s) => {
      scale.value = s
    },
  })

  engine.resize()
  syncFromStore()
  engine.start()

  /*
   * 首屏竞态：GraphCanvas 挂载时 graph.load() 往往还没返回，此时数据为空；
   * 等下一帧再同步一次，覆盖「挂载先于首屏数据到达」的情况。
   * 之后的变更由 watch 负责。
   */
  requestAnimationFrame(() => {
    syncFromStore()
    engine?.zoomToFit()
  })
})

onBeforeUnmount(() => {
  engine?.destroy()
  engine = null
})

/** 把 store 数据推给引擎（挂载与数据变更走同一条路径） */
function syncFromStore() {
  if (!engine) return
  const d = graph.data
  engine.setData({ nodes: [...d.nodes], links: [...d.links] })
}

/*
 * 数据变化 → 重新灌入。
 *
 * 两点很关键：
 *   1. 监听引用本身（shallowRef 整体替换），deep: false —— 深监听会在
 *      物理引擎每帧写坐标时反复触发。
 *   2. 同时监听节点数量。store 里 data 被原地替换时引用一定变；
 *      但若某处直接改了 nodes 数组，引用不变而长度变了，这里也能兜住。
 */
watch(() => graph.data, syncFromStore, { deep: false })
watch(() => graph.nodes.length, syncFromStore)

// 对话侧 hover 引用 chip → 图谱高亮对应节点
watch(
  () => graph.externalFocusId,
  (id) => engine?.focusNode(id),
)

watch(filterType, (t) => engine?.setFilter(t))
watch(showLabels, (v) => engine?.setShowLabels(v))

const TYPE_LABEL: Record<string, string> = {
  session: '会话',
  memory: '记忆',
  document: '文档',
  reason: '推理',
}

const filters: { key: GraphNode['type'] | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'session', label: '会话' },
  { key: 'memory', label: '记忆' },
  { key: 'document', label: '文档' },
  { key: 'reason', label: '推理' },
]

/** 图例和画布共用 glyphs.ts 的几何，避免两套图标走样 */
const legend: { type: GraphNode['type']; label: string }[] = [
  { type: 'session', label: '会话' },
  { type: 'memory', label: '记忆' },
  { type: 'document', label: '文档' },
  { type: 'reason', label: '推理' },
]
</script>

<template>
  <div class="gc">
    <!-- 画布舞台 -->
    <div class="gc__stage">
      <!--
        SVG 渲染容器。不用 canvas：
        CSS :hover 对 canvas 内部无效，暗色要整块重绘，缩放时文字会糊。
        SVG 下这些全部由 CSS 与矢量解决。
      -->
      <div
        ref="hostRef"
        class="gc__canvas"
        role="img"
        :aria-label="graph.a11ySummary"
        tabindex="0"
      ></div>

      <!-- 空态：绝对定位覆盖，不挤占画布尺寸 -->
      <div v-if="graph.isEmpty" class="gc__empty">
        <AppIcon name="link" :size="22" />
        <p>{{ graph.loading ? '加载图谱…' : '暂无关联 · 先进行一段对话' }}</p>
      </div>

      <!-- 悬浮提示 -->
      <div
        v-if="hovered && tooltip.visible"
        class="gc__tip"
        :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
        role="tooltip"
      >
        <p class="gc__tip-type">{{ TYPE_LABEL[hovered.type] }}</p>
        <p class="gc__tip-name">{{ hovered.name }}</p>
        <p class="gc__tip-id">{{ hovered.id }}</p>
        <p v-if="hovered.summary" class="gc__tip-sum">{{ hovered.summary }}</p>
      </div>

      <!-- 控件：右下角，不遮挡主体 -->
      <div class="gc__controls">
        <button
          type="button"
          class="gc__ctl"
          title="放大"
          aria-label="放大"
          @click="engine?.zoomBy(1.25)"
        >
          <AppIcon name="zoom-in" :size="15" />
        </button>
        <button
          type="button"
          class="gc__ctl"
          title="缩小"
          aria-label="缩小"
          @click="engine?.zoomBy(1 / 1.25)"
        >
          <AppIcon name="zoom-out" :size="15" />
        </button>
        <button
          type="button"
          class="gc__ctl"
          title="适应窗口"
          aria-label="适应窗口"
          @click="engine?.zoomToFit()"
        >
          <AppIcon name="maximize" :size="15" />
        </button>
        <button
          type="button"
          class="gc__ctl"
          :class="{ 'is-off': !showLabels }"
          title="显示标签"
          :aria-pressed="showLabels"
          aria-label="显示标签"
          @click="showLabels = !showLabels"
        >
          <AppIcon name="list" :size="15" />
        </button>
        <button
          type="button"
          class="gc__ctl"
          title="重新布局"
          aria-label="重新布局"
          @click="engine?.relayout()"
        >
          <AppIcon name="refresh" :size="15" />
        </button>
      </div>

      <span class="gc__scale tabular">{{ Math.round(scale * 100) }}%</span>
    </div>

    <!-- 图例 + 聚焦模式 -->
    <div class="gc__legend">
      <div class="gc__legend-items">
        <span v-for="item in legend" :key="item.type" class="gc__legend-item">
          <NodeGlyph :type="item.type" :size="14" />
          {{ item.label }}
        </span>
      </div>

      <div class="gc__filters" role="group" aria-label="聚焦模式">
        <button
          v-for="f in filters"
          :key="f.key"
          type="button"
          class="gc__filter"
          :class="{ 'is-active': filterType === f.key }"
          :aria-pressed="filterType === f.key"
          @click="filterType = f.key"
        >
          {{ f.label }}
        </button>
      </div>
    </div>

    <!-- 无障碍等价内容：屏幕阅读器与键盘用户可读的树形列表 -->
    <details class="gc__a11y">
      <summary>以列表形式查看图谱（{{ graph.nodes.length }} 个节点）</summary>
      <ul class="gc__a11y-list">
        <li v-for="n in graph.nodes" :key="n.id">
          <button type="button" class="gc__a11y-item" @click="graph.select(n)">
            <span class="gc__a11y-type">{{ TYPE_LABEL[n.type] }}</span>
            <span class="gc__a11y-name">{{ n.name }}</span>
          </button>
        </li>
      </ul>
    </details>
  </div>
</template>

<style scoped>
.gc {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}

.gc__stage {
  position: relative;
  flex: 1;
  min-height: 200px;
  border-radius: var(--r-md);
  overflow: hidden;
  background-color: var(--surface-overlay);
  /* 纸面方格底：只做背景，不参与 pan / zoom，保持低对比 */
  background-image:
    linear-gradient(
      to right,
      color-mix(in srgb, var(--border-soft) 58%, transparent) 1px,
      transparent 1px
    ),
    linear-gradient(
      to bottom,
      color-mix(in srgb, var(--border-soft) 58%, transparent) 1px,
      transparent 1px
    );
  background-size: 20px 20px;
  user-select: none;
  -webkit-user-select: none;
}

.gc__canvas {
  display: block;
  width: 100%;
  height: 100%;
  cursor: grab;
  touch-action: none;
  position: relative;
  user-select: none;
  -webkit-user-select: none;
}

.gc__canvas :deep(.graph-svg) {
  position: absolute;
  inset: 0;
  user-select: none;
  -webkit-user-select: none;
}

.gc__canvas:active {
  cursor: grabbing;
}

/* 键盘聚焦时给画布描边，而不是浏览器默认轮廓 */
.gc__canvas:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.gc__empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  color: var(--text-tertiary);
  font-size: var(--fs-xs);
  pointer-events: none;
}

/* ---------- 悬浮提示 ---------- */
.gc__tip {
  position: fixed;
  z-index: var(--z-tooltip);
  max-width: 280px;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-md);
  background: var(--surface-inverse);
  color: var(--text-on-dark);
  box-shadow: var(--ef-2);
  pointer-events: none;
}

.gc__tip-type {
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--accent-soft);
}

.gc__tip-name {
  font-size: var(--fs-xs);
  font-weight: var(--fw-medium);
  margin: 1px 0 2px;
}

.gc__tip-id {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-disabled);
  word-break: break-all;
}

.gc__tip-sum {
  margin-top: var(--sp-1);
  font-size: var(--fs-2xs);
  line-height: var(--lh-tight);
  color: #f3ead9;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---------- 控件 ---------- */
.gc__controls {
  position: absolute;
  right: var(--sp-2);
  bottom: var(--sp-2);
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.gc__ctl {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border-soft);
  background: color-mix(in srgb, var(--surface-raised) 88%, transparent);
  backdrop-filter: blur(4px);
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.gc__ctl:hover {
  background: var(--surface-raised);
  color: var(--text-primary);
}

.gc__ctl.is-off {
  opacity: 0.5;
}

.gc__scale {
  position: absolute;
  left: var(--sp-2);
  bottom: var(--sp-2);
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-disabled);
  pointer-events: none;
}

/* ---------- 图例 ---------- */
.gc__legend {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  flex-wrap: wrap;
  padding-top: var(--sp-2);
  flex: 0 0 auto;
}

.gc__legend-items {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.gc__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-2xs);
  color: var(--text-secondary);
}

.gc__filters {
  display: flex;
  gap: 3px;
}

.gc__filter {
  padding: 2px 8px;
  border-radius: var(--r-pill);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-tertiary);
  font-size: 10.5px;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.gc__filter.is-active {
  background: var(--surface-inverse);
  border-color: var(--surface-inverse);
  color: var(--text-on-dark);
}

/* ---------- 无障碍列表 ---------- */
.gc__a11y {
  flex: 0 0 auto;
  margin-top: var(--sp-2);
  font-size: var(--fs-2xs);
}

.gc__a11y summary {
  cursor: pointer;
  color: var(--text-tertiary);
  padding: 3px 0;
}

.gc__a11y summary:hover {
  color: var(--text-secondary);
}

.gc__a11y-list {
  max-height: 160px;
  overflow-y: auto;
  margin-top: var(--sp-1);
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.gc__a11y-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: 3px 6px;
  border: none;
  border-radius: var(--r-sm);
  background: transparent;
  text-align: left;
  font-size: var(--fs-2xs);
  color: var(--text-secondary);
  cursor: pointer;
}

.gc__a11y-item:hover {
  background: var(--surface-sunken);
  color: var(--text-primary);
}

.gc__a11y-type {
  flex: 0 0 auto;
  padding: 0 5px;
  border-radius: var(--r-sm);
  background: var(--surface-sunken);
  font-family: var(--font-mono);
  color: var(--text-tertiary);
}

.gc__a11y-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
