<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import type { Turn, TurnStage } from '@/core/domain/turns'
import { turnDuration } from '@/core/domain/turns'
import { stageLabel } from '@/core/domain/stages'

/**
 * 执行链（头像下方）。
 *
 * 与 TurnTrace 的分工：
 * - **ExecutionChain 是常驻的一行摘要**，让用户扫一眼就知道「这次用了什么、花了多久」；
 * - 展开后才显示逐阶段详情，避免把气泡顶部撑得太高。
 *
 * 阶段与耗时全部来自后端 /trace/stream 的真实事件与时间戳差值。
 */

const props = defineProps<{ turn: Turn }>()

const expanded = ref(false)

const isRunning = computed(() => props.turn.status === 'running')
const isFailed = computed(() => props.turn.status === 'error')
const isAborted = computed(() => props.turn.status === 'aborted')

const duration = computed(() => turnDuration(props.turn))

const stageCount = computed(() => props.turn.stages.length)

/** 引用篇数：阶段详情里累积的 docIds 去重 */
const citedCount = computed(() => {
  const ids = new Set<string>()
  for (const s of props.turn.stages) {
    for (const id of s.detail?.docIds ?? []) ids.add(id)
  }
  return ids.size
})

/** 一句话概括这次执行做了什么（按阶段语义生成） */
const summary = computed(() => {
  const parts: string[] = []
  const has = (key: string) => props.turn.stages.some((s) => s.key === key)

  if (has('classify')) parts.push('理解意图')
  if (has('session_init')) parts.push('唤起记忆')
  if (has('retrieve')) parts.push('检索知识')
  if (has('guided')) parts.push('引导推理')
  if (has('save')) parts.push('保存会话')

  if (!parts.length) {
    if (isRunning.value) return '正在准备…'
    return isFailed.value ? '执行失败' : '已完成'
  }
  return parts.join(' · ')
})

const activeIndex = computed(() => (isRunning.value ? stageCount.value - 1 : -1))

/**
 * 历史回合（从 /session/state 还原）没有 trace 记录，stages 为空。
 * 此时不显示展开箭头 —— 展开后是空白会让用户困惑。
 */
const canExpand = computed(() => stageCount.value > 0)

function fmtDuration(ms: number | null): string {
  if (ms === null) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60_000)}m${Math.round((ms % 60_000) / 1000)}s`
}

function stageState(s: TurnStage, i: number): 'active' | 'done' | 'error' | 'warn' {
  if (s.isError) return 'error'
  if (s.detail?.warn) return 'warn'
  if (i === activeIndex.value) return 'active'
  return 'done'
}

function stateIcon(state: string) {
  switch (state) {
    case 'active':
      return 'clock'
    case 'error':
      return 'close'
    case 'warn':
      return 'alert'
    default:
      return 'check'
  }
}
</script>

<template>
  <div class="chain" :class="[`chain--${turn.status}`]">
    <!-- 常驻摘要行 -->
    <button
      type="button"
      class="chain__summary"
      :class="{ 'is-static': !canExpand }"
      :aria-expanded="canExpand ? expanded : undefined"
      :aria-label="canExpand ? `执行链：${summary}，展开查看详情` : `执行链：${summary}`"
      @click="canExpand && (expanded = !expanded)"
    >
      <span class="chain__pulse" :class="{ 'is-running': isRunning }" aria-hidden="true">
        <AppIcon
          :name="isFailed ? 'alert' : isAborted ? 'stop' : isRunning ? 'clock' : 'check'"
          :size="10"
        />
      </span>

      <span class="chain__text">{{ summary }}</span>

      <span v-if="citedCount" class="chain__badge" :title="`引用了 ${citedCount} 篇文档`">
        <AppIcon name="quote" :size="10" />
        {{ citedCount }}
      </span>

      <span v-if="duration" class="chain__time tabular">{{ fmtDuration(duration) }}</span>

      <AppIcon
        v-if="canExpand"
        name="chevron-right"
        :size="10"
        class="chain__caret"
        :class="{ 'is-open': expanded }"
      />
    </button>

    <!-- 展开：逐阶段 -->
    <Transition name="chain-expand">
      <ol v-if="expanded && canExpand" class="chain__steps">
        <li
          v-for="(s, i) in turn.stages"
          :key="i"
          class="chain__step"
          :class="`chain__step--${stageState(s, i)}`"
        >
          <span class="chain__node" aria-hidden="true">
            <AppIcon :name="stateIcon(stageState(s, i))" :size="8" />
          </span>

          <span class="chain__name">{{ stageLabel(s.raw) }}</span>

          <span v-if="s.detail?.badge" class="chain__tag">{{ s.detail.badge }}</span>
          <span v-else-if="s.detail?.summary" class="chain__detail">{{ s.detail.summary }}</span>

          <span class="chain__dur tabular">{{ fmtDuration(s.durationMs) }}</span>
        </li>

        <li v-if="isRunning" class="chain__step chain__step--pending">
          <span class="chain__node" aria-hidden="true"></span>
          <span class="chain__name chain__ghost"></span>
        </li>

        <li v-if="turn.error && (isFailed || isAborted)" class="chain__error">
          {{ turn.error }}
        </li>
      </ol>
    </Transition>
  </div>
</template>

<style scoped>
.chain {
  margin-bottom: var(--sp-2);
}

/* ---------- 摘要行 ---------- */
.chain__summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px 3px 5px;
  border-radius: var(--r-pill);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--fs-2xs);
  line-height: 1.5;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.chain__summary:hover {
  background: var(--surface);
  border-color: var(--border-soft);
  color: var(--text-secondary);
}

/* 不可展开时不给 hover 反馈，避免暗示可点 */
.chain__summary.is-static {
  cursor: default;
}

.chain__summary.is-static:hover {
  background: transparent;
  border-color: transparent;
  color: var(--text-tertiary);
}

.chain--running .chain__summary {
  border-color: var(--border-soft);
  background: var(--surface);
}

/* 状态脉冲点 */
.chain__pulse {
  display: grid;
  place-items: center;
  width: 15px;
  height: 15px;
  flex: 0 0 15px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--success) 15%, transparent);
  color: var(--success);
}

.chain--running .chain__pulse {
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
}

.chain--error .chain__pulse {
  background: var(--surface-danger-ghost);
  color: var(--danger);
}

.chain--aborted .chain__pulse {
  background: var(--surface-sunken);
  color: var(--text-tertiary);
}

.chain__pulse.is-running {
  animation: chain-pulse 1.5s ease-in-out infinite;
}

@keyframes chain-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

.chain__text {
  font-weight: var(--fw-medium);
  white-space: nowrap;
}

.chain__badge {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 0 5px;
  border-radius: var(--r-pill);
  background: color-mix(in srgb, var(--entity-document) 12%, transparent);
  color: #3f5a57;
  font-family: var(--font-mono);
}

.chain__time {
  font-family: var(--font-mono);
  color: var(--text-tertiary);
}

.chain__caret {
  color: var(--text-disabled);
  transition: transform var(--dur-base) var(--ease-out);
}

.chain__caret.is-open {
  transform: rotate(90deg);
}

/* ---------- 展开的步骤列表 ---------- */
.chain__steps {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin: 4px 0 0 7px;
  padding-left: var(--sp-3);
  border-left: 1px solid var(--border-soft);
}

.chain__step {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  font-size: var(--fs-2xs);
  color: var(--text-secondary);
  position: relative;
}

/* 节点圆点压住竖线 */
.chain__node {
  position: absolute;
  left: calc(var(--sp-3) * -1 - 1px);
  display: grid;
  place-items: center;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  color: var(--success);
}

.chain__step--active .chain__node {
  border-color: var(--accent);
  color: var(--accent-deep);
}

.chain__step--error .chain__node {
  border-color: var(--danger);
  color: var(--danger);
}

.chain__step--warn .chain__node {
  border-color: var(--warning);
  color: var(--warning);
}

.chain__step--pending .chain__node {
  border-style: dashed;
}

.chain__name {
  color: var(--text-primary);
  white-space: nowrap;
}

.chain__tag {
  padding: 0 5px;
  border-radius: var(--r-sm);
  background: var(--surface-sunken);
  font-family: var(--font-mono);
  color: var(--text-secondary);
}

.chain__detail {
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chain__dur {
  margin-left: auto;
  font-family: var(--font-mono);
  color: var(--text-tertiary);
  white-space: nowrap;
}

.chain__ghost {
  display: inline-block;
  width: 56px;
  height: 8px;
  border-radius: var(--r-pill);
  background: var(--surface-sunken);
}

.chain__error {
  margin-top: 3px;
  padding: 3px 7px;
  border-radius: var(--r-sm);
  background: var(--surface-danger-ghost);
  color: var(--danger);
  font-size: var(--fs-2xs);
}

/* ---------- 展开动画 ---------- */
.chain-expand-enter-active,
.chain-expand-leave-active {
  transition: opacity var(--dur-base) var(--ease-out);
}

.chain-expand-enter-from,
.chain-expand-leave-to {
  opacity: 0;
}

@media (max-width: 720px) {
  .chain__text {
    max-width: 40vw;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
</style>
