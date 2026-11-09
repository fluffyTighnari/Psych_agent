<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import ViewHeader from '@/components/layout/ViewHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppDisclosure from '@/components/ui/AppDisclosure.vue'
import AppEmpty from '@/components/ui/AppEmpty.vue'
import AppSkeleton from '@/components/ui/AppSkeleton.vue'
import { TraceStream, type TraceStatus } from '@/core/stream/trace-stream'
import { useTraceStore } from '@/stores/trace'
import type { TraceItem } from '@/core/api/types'

const trace = useTraceStore()
const status = ref<TraceStatus>('connecting')
const autoScroll = ref(true)
const listRef = ref<HTMLElement | null>(null)

let stream: TraceStream | null = null

const statusText = computed(() => {
  switch (status.value) {
    case 'open':
      return 'SSE 监听中'
    case 'connecting':
      return '连接中…'
    case 'error':
      return '连接中断（重连中）'
    default:
      return '已断开'
  }
})

const isEmpty = computed(() => !trace.loading && trace.count === 0)

onMounted(async () => {
  await trace.loadAll()

  stream = new TraceStream({
    onFrame: (frame) => {
      // 只累积，不按 version 重置（见 core/stream/trace-stream.ts 注释）
      const added = trace.add(frame.logs)
      if (added && autoScroll.value) scrollToBottom()
    },
    onStatus: (s) => {
      status.value = s
    },
  })
  stream.connect()
})

onBeforeUnmount(() => {
  stream?.disconnect()
  stream = null
})

function scrollToBottom() {
  requestAnimationFrame(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function stageTone(item: TraceItem) {
  if (item.is_error) return 'error' as const
  return 'default' as const
}

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}

function contentRows(item: TraceItem) {
  return Object.entries(item.content ?? {})
}

function formatValue(v: unknown) {
  return typeof v === 'object' && v !== null ? JSON.stringify(v, null, 2) : String(v)
}

async function refresh() {
  await trace.loadAll()
  scrollToBottom()
}
</script>

<template>
  <div class="app-view">
    <ViewHeader>
      <template #actions>
        <div class="status" :class="`status--${status}`" role="status" aria-live="polite">
          <span class="status__dot" aria-hidden="true"></span>
          {{ statusText }}
        </div>
        <AppButton size="sm" icon="arrow-down" @click="scrollToBottom">滚到底部</AppButton>
        <AppButton size="sm" icon="refresh" @click="refresh">刷新</AppButton>
        <AppButton size="sm" :disabled="trace.count === 0" @click="trace.clear()">清空视图</AppButton>
      </template>
    </ViewHeader>

    <p class="hint">
      共 {{ trace.count }} 条 · 版本 {{ trace.version }} · 仅累积新增，不因版本变更重置
    </p>

    <div ref="listRef" class="trace-list">
      <AppSkeleton v-if="trace.loading" :lines="5" />

      <AppEmpty
        v-else-if="isEmpty"
        icon="pulse"
        title="暂无日志"
        desc="发起一次对话或检索后会自动记录处理阶段"
      />

      <AppEmpty
        v-else-if="trace.error"
        icon="alert"
        tone="error"
        title="日志加载失败"
        :desc="trace.error"
      >
        <AppButton size="sm" variant="primary" icon="refresh" @click="refresh">重试</AppButton>
      </AppEmpty>

      <AppDisclosure
        v-for="(item, i) in trace.logs"
        :key="`${item.timestamp}-${item.stage}-${i}`"
        :label="item.label || item.stage"
        :meta="fmtTime(item.timestamp)"
        :tone="stageTone(item)"
        :has-detail="item.is_error || contentRows(item).length > 0"
        :open="item.is_error"
        variant="line"
      >
        <template #meta>
          <span class="stage">{{ item.stage }}</span>
        </template>

        <pre v-if="item.is_error" class="err">{{ item.error_msg || '未知错误' }}</pre>

        <dl v-if="contentRows(item).length" class="kv">
          <template v-for="[k, v] in contentRows(item)" :key="k">
            <dt>{{ k }}</dt>
            <dd :class="{ 'is-json': typeof v === 'object' && v !== null }">{{ formatValue(v) }}</dd>
          </template>
        </dl>
      </AppDisclosure>
    </div>
  </div>
</template>

<style scoped>
.status {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.status__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-tertiary);
}

.status--open .status__dot {
  background: var(--success);
}

.status--error .status__dot {
  background: var(--danger);
}

.status--connecting .status__dot {
  background: var(--warning);
}

/*
 * 「共 8 条 · 版本 16 · 仅累积新增…」这类说明是给人读的中文句子，
 * 不是 ID 也不是表格数据 —— 塞进等宽栈、还压到 12.5px 就成了一层灰雾。
 * 改回正文字体，并与页头副标题（「检索你的知识文档与历史会话记忆」）同字号。
 */
.hint {
  margin: var(--sp-3) 0 var(--sp-2);
  font-family: var(--font-sans);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.trace-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding-bottom: var(--sp-5);
}

.stage {
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  padding: 2px 8px;
  border-radius: var(--r-sm);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  white-space: nowrap;
}

.err {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--danger);
  background: var(--surface-danger-ghost);
  padding: var(--sp-2);
  border-radius: var(--r-sm);
  white-space: pre-wrap;
  word-break: break-word;
}

.kv {
  display: grid;
  grid-template-columns: minmax(80px, 140px) minmax(0, 1fr);
  gap: 4px var(--sp-3);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.kv dt {
  color: var(--accent-deep);
  word-break: break-word;
}

.kv dd {
  color: var(--text-secondary);
  word-break: break-word;
}

.kv dd.is-json {
  white-space: pre-wrap;
  background: var(--surface);
  padding: var(--sp-1) var(--sp-2);
  border-radius: var(--r-sm);
}
</style>
