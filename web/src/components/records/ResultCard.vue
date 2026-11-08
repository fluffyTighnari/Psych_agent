<script setup lang="ts">
import { computed, ref } from 'vue'
import AppDisclosure from '@/components/ui/AppDisclosure.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import HighlightText from './HighlightText.vue'
import type { Document, Emotion, Memory } from '@/core/api/types'

/**
 * 检索结果卡。
 * 文档与记忆共用一套外壳，按类型切换正文区块 —— 两者字段结构差异大，
 * 但「标题 + 徽章 + 摘要 + chips + 可展开详情」的骨架是一致的。
 */

const props = defineProps<{
  item: Document | Memory
  kind: 'document' | 'memory'
  /** 高亮词（target_text / 关键词） */
  terms?: string[]
}>()

const emit = defineEmits<{
  /** 展开卡片（就地看详情） */
  open: [item: Document | Memory]
  /** 在页面级侧滑里阅读全文（宽度足够，适合长文） */
  readFull: [item: Document | Memory]
  askInChat: [item: Document | Memory]
  insertToWeekly: [item: Document | Memory]
}>()

const open = ref(false)

const doc = computed<Document | null>(() => (props.kind === 'document' ? (props.item as Document) : null))
const mem = computed<Memory | null>(() => (props.kind === 'memory' ? (props.item as Memory) : null))

const title = computed(() => {
  if (doc.value) return doc.value.title || doc.value.doc_id || '无标题'
  return mem.value?.title || '（无标题）'
})

const summary = computed(() => {
  if (doc.value) return doc.value.summary || '（无摘要）'
  return mem.value?.summary || '（无摘要）'
})

const topics = computed<string[]>(() => {
  if (doc.value) return Array.isArray(doc.value.topic) ? doc.value.topic : []
  return Array.isArray(mem.value?.topics) ? mem.value!.topics : []
})

const keywords = computed<string[]>(() => {
  if (doc.value) return Array.isArray(doc.value.keywords) ? doc.value.keywords : []
  return Array.isArray(mem.value?.keywords) ? mem.value!.keywords : []
})

const emotion = computed<Emotion | null>(() => {
  const e = doc.value?.emotion ?? mem.value?.emotion
  return e && Object.keys(e).length ? e : null
})

function emotionText(e: Emotion): string {
  const p = e.primary || e.primary_emotion || '—'
  const s = e.secondary || e.secondary_emotion || ''
  const i = typeof e.intensity === 'number' ? ` (${Math.round(e.intensity * 100)}%)` : ''
  return s ? `${p} · ${s}${i}` : `${p}${i}`
}

const dateText = computed(() => {
  if (doc.value?.date) return doc.value.date
  if (mem.value) return `${(mem.value.start_time || '').slice(0, 16)} ~ ${(mem.value.end_time || '').slice(0, 16)}`
  return ''
})

/** 所有高亮词：关键词 + 主题 */
const allTerms = computed(() => [...(props.terms ?? []), ...keywords.value])
</script>

<template>
  <AppDisclosure
    v-model:open="open"
    :label="title"
    :has-detail="true"
    variant="card"
    @update:open="(v: boolean) => v && emit('open', item)"
  >
    <template #meta>
      <span v-if="kind === 'document' && doc?.doc_type" class="rc__badge" :class="`rc__badge--${doc.doc_type}`">
        {{ doc.doc_type }}
      </span>
      <span v-else-if="kind === 'memory'" class="rc__badge rc__badge--memory">memory</span>
      <span v-if="dateText" class="rc__date">{{ dateText }}</span>
    </template>

    <!--
      摘要与 chips 放在常显区：
      结果列表是扫读场景，收起时必须能看到内容概要，
      否则 31 条结果只显示日期，等于没有信息。
    -->
    <template #preview>
      <p class="rc__summary">
        <HighlightText :text="summary" :terms="allTerms" :max-len="open ? 0 : 220" />
      </p>

      <div class="rc__meta">
        <span v-for="t in topics" :key="'t' + t" class="rc__chip rc__chip--topic">{{ t }}</span>
        <span v-for="k in keywords" :key="'k' + k" class="rc__chip rc__chip--kw">{{ k }}</span>
        <span v-if="emotion" class="rc__chip rc__chip--emo">{{ emotionText(emotion) }}</span>
      </div>
    </template>

    <!-- 展开详情 -->
    <div class="rc__detail">
      <template v-if="doc">
        <template v-if="doc.doc_type === 'weekly'">
          <h5>problem · 问题</h5>
          <p class="rc__body"><HighlightText :text="doc.problem || '—'" :terms="allTerms" /></p>
          <h5>analysis · 分析</h5>
          <p class="rc__body"><HighlightText :text="doc.analysis || '—'" :terms="allTerms" /></p>
          <h5>solution · 方案</h5>
          <p class="rc__body"><HighlightText :text="doc.solution || '—'" :terms="allTerms" /></p>
        </template>
        <template v-else>
          <h5>正文</h5>
          <p class="rc__body"><HighlightText :text="doc.content || '—'" :terms="allTerms" /></p>
        </template>
        <h5>来源</h5>
        <p class="rc__path">{{ doc.relative_path || doc.source || '—' }}</p>
      </template>

      <template v-else-if="mem">
        <h5>记忆 ID</h5>
        <p class="rc__path">{{ mem.id }}</p>

        <template v-if="mem.insights?.length">
          <h5>核心洞察</h5>
          <p class="rc__body">{{ mem.insights.join('；') }}</p>
        </template>

        <template v-if="mem.referenced_documents?.length">
          <h5>引用文档</h5>
          <p class="rc__path">{{ mem.referenced_documents.join('、') }}</p>
        </template>

        <template v-if="mem.dialogues?.length">
          <h5>对话记录（{{ mem.dialogues.length }} 条）</h5>
          <div class="rc__dialogues">
            <div
              v-for="(d, i) in mem.dialogues"
              :key="i"
              class="rc__dlg"
              :class="`rc__dlg--${d.role === 'user' ? 'user' : 'assistant'}`"
            >
              <span class="rc__dlg-role">{{ d.role === 'user' ? '我' : '咨询师' }}</span>
              <p class="rc__dlg-text">{{ d.content }}</p>
            </div>
          </div>
        </template>
      </template>

      <!-- 动作 -->
      <div class="rc__actions">
        <button type="button" class="rc__action rc__action--primary" @click.stop="emit('readFull', item)">
          <AppIcon name="maximize" :size="12" />
          阅读全文
        </button>
        <button type="button" class="rc__action" @click.stop="emit('askInChat', item)">
          <AppIcon name="chat" :size="12" />
          在对话中追问
        </button>
        <button type="button" class="rc__action" @click.stop="emit('insertToWeekly', item)">
          <AppIcon name="pen" :size="12" />
          摘入周记
        </button>
      </div>
    </div>
  </AppDisclosure>
</template>

<style scoped>
.rc__badge {
  padding: 1px 7px;
  border-radius: var(--r-sm);
  font-family: var(--font-mono);
  font-size: 11.5px;
  white-space: nowrap;
}

.rc__badge--daily {
  background: rgba(78, 109, 106, 0.12);
  color: #3f5a57;
}

.rc__badge--weekly {
  background: var(--surface-warning-ghost);
  color: var(--warning);
}

.rc__badge--memory {
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
}

.rc__date {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

/* 记录页是阅读界面，摘要按正文对待（14.5px），不用工具界面的小字 */
.rc__summary {
  font-size: 14.5px;
  line-height: 1.8;
  color: var(--text-secondary);
  margin-bottom: var(--sp-2);
}

.rc__meta {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: var(--sp-1);
}

.rc__chip {
  padding: 1px 7px;
  border-radius: var(--r-pill);
  font-size: 12px;
}

.rc__chip--topic {
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
}

.rc__chip--kw {
  background: rgba(78, 109, 106, 0.1);
  color: #3f5a57;
}

.rc__chip--emo {
  background: var(--surface-warning-ghost);
  color: var(--warning);
}

/* ---------- 详情 ---------- */
.rc__detail h5 {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: var(--fw-medium);
  color: var(--text-tertiary);
  letter-spacing: 0.3px;
  margin: var(--sp-2) 0 2px;
}

.rc__detail h5:first-child {
  margin-top: 0;
}

.rc__body {
  font-size: 14.5px;
  line-height: 1.85;
  color: var(--text-secondary);
}

.rc__path {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-tertiary);
  word-break: break-all;
}

/* ---------- 对话记录 ---------- */
.rc__dialogues {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  margin-top: var(--sp-1);
}

.rc__dlg {
  max-width: 92%;
  padding: 5px 9px;
  border-radius: var(--r-sm);
}

.rc__dlg--user {
  align-self: flex-end;
  background: var(--surface-inverse);
  color: var(--text-on-dark);
}

.rc__dlg--assistant {
  align-self: flex-start;
  background: var(--surface-sunken);
}

.rc__dlg-role {
  display: block;
  font-size: 11px;
  opacity: 0.65;
  margin-bottom: 1px;
}

.rc__dlg-text {
  font-size: 13.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---------- 动作 ---------- */
.rc__actions {
  display: flex;
  gap: var(--sp-1);
  margin-top: var(--sp-3);
  padding-top: var(--sp-2);
  border-top: 1px dashed var(--border-soft);
}

.rc__action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.rc__action:hover {
  background: var(--surface-sunken);
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.rc__action--primary {
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
  color: var(--accent-deep);
}

.rc__action--primary:hover {
  background: var(--surface-accent-ghost);
  border-color: var(--accent);
  color: var(--accent-deep);
}
</style>
