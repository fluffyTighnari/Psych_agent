<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Turn } from '@/core/domain/turns'
import { turnCitationIds, turnSummary } from '@/core/domain/turns'

/**
 * 会话内导航刻度轨。
 *
 * 只有一个形态：竖直刻度轨。早先还有个可展开的「对话大纲」面板，
 * 已删除 —— 它和刻度轨功能重叠，展开后反而挤占对话宽度。
 *
 * 强化后的设计：
 * - 刻度之间用连接线串成一条「链路」，而不是散点；
 * - 每种轮次类型有独立形状（普通/引导/报告/含引用），不只靠颜色；
 * - 当前视口所在轮次明显高亮，hover 显示该轮提问摘要；
 * - 点击平滑滚动到对应轮次。
 */

const props = defineProps<{
  turns: Turn[]
  /** 当前视口所在 Turn 的 id */
  activeId: string | null
}>()

const emit = defineEmits<{
  jump: [turnId: string]
}>()

const hoveredId = ref<string | null>(null)

type MarkKind = 'normal' | 'guided' | 'report' | 'cited'

interface RailItem {
  turn: Turn
  kind: MarkKind
  label: string
}

const items = computed<RailItem[]>(() =>
  props.turns.map((t) => {
    const cited = turnCitationIds(t).length > 0
    const isGuide = t.speaker === 'guide'
    const hasReport = t.reply.includes('【建议总结】')

    let kind: MarkKind = 'normal'
    if (hasReport) kind = 'report'
    else if (isGuide) kind = 'guided'
    else if (cited) kind = 'cited'

    return { turn: t, kind, label: turnSummary(t, 46) }
  }),
)

const KIND_LABEL: Record<MarkKind, string> = {
  normal: '对话',
  guided: '引导',
  report: '建议报告',
  cited: '含引用',
}

const hoveredLabel = computed(() => {
  const item = items.value.find((i) => i.turn.id === hoveredId.value)
  return item?.label ?? ''
})

/**
 * hover 摘要的垂直位置：跟着被指的刻度走，而不是钉在轨道顶部。
 *
 * 原先浮层固定 `top: --sp-2`，鼠标停在第 12 个刻度上，摘要却出现在最上面，
 * 中间隔着十几行 —— 完全看不出这条摘要对应哪一点。
 * 现在取刻度中心相对轨道的偏移，并把浮层垂直居中到那个位置。
 */
const railRef = ref<HTMLElement | null>(null)
const hoveredTop = ref(0)

function showTip(turnId: string, e: Event) {
  hoveredId.value = turnId
  const railEl = railRef.value
  const markEl = e.currentTarget as HTMLElement | null
  if (!railEl || !markEl) return
  const mr = markEl.getBoundingClientRect()
  const rr = railEl.getBoundingClientRect()
  const center = mr.top - rr.top + mr.height / 2
  // 夹进轨道范围，避免首尾刻度时浮层跑出可视区
  hoveredTop.value = Math.min(Math.max(center, 28), Math.max(28, rr.height - 28))
}
</script>

<template>
  <div v-if="items.length" ref="railRef" class="rail-ticks" role="navigation" aria-label="会话内导航">
    <!-- hover 摘要浮层：垂直跟随被指的刻度 -->
    <Transition name="tip">
      <div
        v-if="hoveredId && hoveredLabel"
        class="rail-ticks__tip"
        :style="{ top: `${hoveredTop}px` }"
        role="tooltip"
      >
        {{ hoveredLabel }}
      </div>
    </Transition>

    <div class="rail-ticks__list">
      <div
        v-for="(item, i) in items"
        :key="item.turn.id"
        class="rail-ticks__slot"
      >
        <!-- 连接线：把相邻刻度串成链路 -->
        <span
          v-if="i > 0"
          class="rail-ticks__link"
          :class="{ 'is-lit': item.turn.id === activeId || items[i - 1]?.turn.id === activeId }"
          aria-hidden="true"
        ></span>

        <button
          type="button"
          class="mark"
          :class="[
            `mark--${item.kind}`,
            {
              'is-current': item.turn.id === activeId,
              'is-hovered': item.turn.id === hoveredId,
            },
          ]"
          :title="`${KIND_LABEL[item.kind]}：${item.label}`"
          :aria-label="`跳到第 ${i + 1} 轮：${item.label}`"
          :aria-current="item.turn.id === activeId ? 'true' : undefined"
          @click="emit('jump', item.turn.id)"
          @mouseenter="showTip(item.turn.id, $event)"
          @mouseleave="hoveredId = null"
          @focus="showTip(item.turn.id, $event)"
          @blur="hoveredId = null"
        >
          <span class="mark__shape" aria-hidden="true"></span>
          <span v-if="item.kind === 'report'" class="mark__badge" aria-hidden="true"></span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rail-ticks {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 34px;
  flex: 0 0 34px;
  padding-top: var(--sp-2);
  /* 浮层要向左伸出容器，不能被裁切 */
  overflow: visible;
}

/* ---------- hover 摘要 ---------- */
/*
 * hover 摘要浮层。
 *
 * 两条约束：
 * ① 轨道容器只有 34px 宽，浮层必须**向左自由展开**而不被父级裁切
 *    （父级 overflow: visible，浮层给 min-width 并可换行）。
 * ② 垂直位置必须跟着被指的刻度走。原先固定 top: --sp-2，
 *    停在第十二个刻度上摘要却出现在最上面，隔了十几行，看不出对应关系。
 *    现在 top 由 JS 写入刻度中心偏移，这里 translateY(-50%) 居中到刻度上。
 */
.rail-ticks__tip {
  position: absolute;
  right: calc(100% + 8px);
  transform: translateY(-50%);
  width: max-content;
  min-width: 140px;
  max-width: 260px;
  padding: 7px 11px;
  border-radius: var(--r-md);
  background: var(--surface-inverse);
  color: var(--text-on-dark);
  font-size: var(--fs-2xs);
  line-height: 1.5;
  /* 正常换行，不再逐字断行 */
  white-space: normal;
  word-break: break-word;
  box-shadow: var(--ef-2);
  z-index: var(--z-tooltip);
  pointer-events: none;
}

.tip-enter-active,
.tip-leave-active {
  transition: opacity var(--dur-fast) var(--ease-out);
}

.tip-enter-from,
.tip-leave-to {
  opacity: 0;
}

/* ---------- 轨道 ---------- */
.rail-ticks__list {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--sp-1) 0;
  max-height: 70vh;
  overflow-y: auto;
  scrollbar-width: none;
}

.rail-ticks__list::-webkit-scrollbar {
  display: none;
}

.rail-ticks__slot {
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* 连接线：强化「链路」感，而不是孤立圆点 */
.rail-ticks__link {
  width: 1.5px;
  height: 14px;
  background: var(--border);
  border-radius: 1px;
  transition:
    background var(--dur-base) var(--ease-out),
    height var(--dur-base) var(--ease-out);
}

/* 当前轮次相邻的连接线加亮，形成「已走到这里」的指示 */
.rail-ticks__link.is-lit {
  background: var(--accent);
  opacity: 0.55;
}

/* ---------- 刻度 ---------- */
.mark {
  display: grid;
  place-items: center;
  width: 22px;
  height: 20px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  position: relative;
}

.mark__shape {
  display: block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: var(--border-strong);
  transition:
    background var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}

/* 形状编码：不只用颜色区分 */
.mark--guided .mark__shape {
  transform: rotate(45deg);
  border-radius: 1px;
  background: var(--entity-reason);
  opacity: 0.75;
}

.mark--cited .mark__shape {
  border-radius: 50%;
  background: var(--entity-document);
  opacity: 0.8;
}

/* 报告：更宽的横条 + 右上角小点，一眼可辨 */
.mark--report .mark__shape {
  width: 14px;
  height: 6px;
  border-radius: 1px;
  background: var(--accent);
}

.mark__badge {
  position: absolute;
  top: 4px;
  right: 3px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--accent-deep);
}

/* ---------- 状态 ---------- */
.mark:hover .mark__shape,
.mark.is-hovered .mark__shape {
  transform: scale(1.35);
  background: var(--text-secondary);
  opacity: 1;
}

.mark--guided:hover .mark__shape,
.mark--guided.is-hovered .mark__shape {
  transform: rotate(45deg) scale(1.35);
}

.mark--report:hover .mark__shape,
.mark--report.is-hovered .mark__shape {
  transform: scale(1.15);
}

/* 当前轮次：明显放大 + 光晕 */
.mark.is-current .mark__shape {
  background: var(--accent);
  opacity: 1;
  transform: scale(1.6);
  box-shadow: 0 0 0 3px var(--surface-accent-ghost);
}

.mark--guided.is-current .mark__shape {
  transform: rotate(45deg) scale(1.6);
}

.mark--report.is-current .mark__shape {
  transform: scale(1.35);
}

/* 键盘焦点可见环 */
.mark:focus-visible {
  border-radius: 50%;
  box-shadow: var(--focus-ring);
}
</style>
