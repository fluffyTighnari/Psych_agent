<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import HighlightText from '@/components/records/HighlightText.vue'
import { toastOk } from '@/components/ui/useToast'
import { usePeekStore } from '@/stores/peek'
import { useWriteStore } from '@/stores/write'
import { useChatBridgeStore } from '@/stores/chatBridge'
import type { Emotion } from '@/core/api/types'

/**
 * 文档预览侧滑（Page-level Peek）。
 *
 * 解决的问题：文档被引用时看不到原文 —— 检索调试的最终结果点不动、
 * 聊天引用的 Inspector 只有摘要。原先阅读器嵌在图谱面板内（240px），
 * 无论图谱怎么调宽都装不下正文。
 *
 * 这里是**页面级图层**，宽度与图谱无关（默认 50vw），覆盖在内容之上。
 * 用侧滑而非弹窗：读文档时本就不在对话，侧滑保留「从哪来」的空间记忆；
 * 用覆盖而非跳转：不丢失当前上下文（在调试检索不该被扔到记录页）。
 */

const peek = usePeekStore()
const chatBridge = useChatBridgeStore()
const write = useWriteStore()
const router = useRouter()
const route = useRoute()

const scrollRef = ref<HTMLElement | null>(null)
const rootRef = ref<HTMLElement | null>(null)
/** 按文档 id 记住各自的滚动位置，切换时不互相干扰 */
const scrollMemory = new Map<string, number>()

let resizing = false
let startX = 0
let startW = 0

const viewportW = ref(typeof window !== 'undefined' ? window.innerWidth : 1400)
const panelWidth = computed(() => peek.resolvedWidth(viewportW.value))

const doc = computed(() => (peek.target?.kind === 'document' ? peek.target.doc : null))
const memory = computed(() => (peek.target?.kind === 'memory' ? peek.target.memory : null))

const currentKey = computed(() => doc.value?.doc_id ?? memory.value?.id ?? '')

const isWeekly = computed(() => doc.value?.doc_type === 'weekly')

const dateText = computed(() => {
  if (doc.value?.date) return doc.value.date
  if (memory.value) {
    return `${(memory.value.start_time || '').slice(0, 16)} ~ ${(memory.value.end_time || '').slice(0, 16)}`
  }
  return ''
})

const sourcePath = computed(() => doc.value?.relative_path || doc.value?.source || '')

const topics = computed<string[]>(() =>
  doc.value ? (Array.isArray(doc.value.topic) ? doc.value.topic : []) : (memory.value?.topics ?? []),
)

const keywords = computed<string[]>(() =>
  doc.value ? (Array.isArray(doc.value.keywords) ? doc.value.keywords : []) : (memory.value?.keywords ?? []),
)

const emotion = computed<Emotion | null>(() => {
  const e = doc.value?.emotion ?? memory.value?.emotion
  return e && Object.keys(e).length ? e : null
})

function emotionText(e: Emotion): string {
  const p = e.primary || e.primary_emotion || '—'
  const s = e.secondary || e.secondary_emotion || ''
  const i = typeof e.intensity === 'number' ? ` (${Math.round(e.intensity * 100)}%)` : ''
  return s ? `${p} · ${s}${i}` : `${p}${i}`
}

/** 全文纯文本（复制用） */
const fullText = computed(() => {
  if (doc.value) {
    if (isWeekly.value) {
      return [
        doc.value.title,
        '',
        '【问题】',
        doc.value.problem || '',
        '',
        '【分析】',
        doc.value.analysis || '',
        '',
        '【方案】',
        doc.value.solution || '',
      ].join('\n')
    }
    return [doc.value.title, '', doc.value.content || ''].join('\n')
  }
  if (memory.value) {
    return [memory.value.title, '', memory.value.summary || ''].join('\n')
  }
  return ''
})

/* ---------- 键盘 ---------- */

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && peek.isOpen) {
    e.stopPropagation()
    peek.close()
  }
}

/* ---------- 拖拽调宽 ---------- */

function onResizeStart(e: PointerEvent) {
  resizing = true
  startX = e.clientX
  startW = panelWidth.value
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
}

function onResizeMove(e: PointerEvent) {
  if (!resizing) return
  // 向左拖 = 变宽
  const delta = startX - e.clientX
  peek.setWidth(startW + delta)
}

function onResizeEnd(e: PointerEvent) {
  if (!resizing) return
  resizing = false
  try {
    ;(e.target as HTMLElement).releasePointerCapture(e.pointerId)
  } catch {
    // 指针已释放
  }
}

/* ---------- 滚动位置记忆 ---------- */

function restoreScroll() {
  const el = scrollRef.value
  if (!el) return
  el.scrollTop = scrollMemory.get(currentKey.value) ?? 0
}

function onScroll() {
  if (currentKey.value) scrollMemory.set(currentKey.value, scrollRef.value?.scrollTop ?? 0)
}

watch(currentKey, () => {
  requestAnimationFrame(restoreScroll)
})

watch(
  () => peek.isOpen,
  (open) => {
    if (!open) return
    // 打开时把焦点移到面板，Esc 才能立刻生效
    requestAnimationFrame(() => {
      rootRef.value?.focus()
      restoreScroll()
    })
  },
)

/* ---------- 动作 ---------- */

async function onCopyAll() {
  try {
    await navigator.clipboard.writeText(fullText.value)
    toastOk('已复制全文')
  } catch {
    toastOk('当前环境不支持剪贴板')
  }
}

/** 复制当前选中片段 */
async function onCopySelection() {
  const sel = window.getSelection()?.toString().trim()
  if (!sel) {
    toastOk('先选中要复制的片段')
    return
  }
  try {
    await navigator.clipboard.writeText(sel)
    toastOk(`已复制 ${sel.length} 字`)
  } catch {
    toastOk('当前环境不支持剪贴板')
  }
}

function onAskInChat() {
  const d = doc.value
  const m = memory.value
  const title = d?.title ?? m?.title ?? ''

  // 文档优先传全文，让 LLM 能直接基于内容回答；记忆只能传摘要
  const content = d
    ? isWeekly.value
      ? [d.problem, d.analysis, d.solution].filter(Boolean).join('\n\n')
      : d.content || d.summary || ''
    : m?.summary || ''

  if (!content.trim()) {
    toastOk('该内容为空，无法引用')
    return
  }

  chatBridge.attach({
    id: `doc-${d?.doc_id ?? m?.id ?? title}`,
    kind: 'document',
    doc_id: d?.doc_id,
    title: title || '未命名',
    content,
  })

  peek.close()
  void router.push({ name: 'chat' })
  toastOk(`已附上《${title}》· 直接提问即可`, 4000)
}

function onInsertToWeekly() {
  const t = doc.value?.title ?? memory.value?.title ?? ''
  const body =
    doc.value?.content ||
    (isWeekly.value
      ? [doc.value?.problem, doc.value?.analysis, doc.value?.solution].filter(Boolean).join('\n\n')
      : doc.value?.summary) ||
    memory.value?.summary ||
    ''

  const quote = body
    .split('\n')
    .map((l) => (l.trim() ? `> ${l}` : '>'))
    .join('\n')

  const block = `\n\n> 来自《${t}》\n\n${quote}\n\n`
  write.setSection('analysis', write.analysis + block)
  toastOk('已摘入周记 · analysis 段', 4000)
}

/* ---------- 生命周期 ---------- */

function onWindowResize() {
  viewportW.value = window.innerWidth
}

/*
 * 路由切换时关闭面板。
 * 不关会导致遮罩残留在新页面上，用户点不动任何东西 —— 这是加遮罩后
 * 必须配套处理的生命周期职责。
 */
watch(
  () => route.fullPath,
  () => {
    if (peek.isOpen) peek.close()
  },
)

onMounted(() => {
  document.addEventListener('keydown', onKeydown, true)
  window.addEventListener('resize', onWindowResize)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown, true)
  window.removeEventListener('resize', onWindowResize)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="peek">
      <!--
        遮罩：点击空白处关闭。
        与「从对话摘取」抽屉行为一致 —— 侧滑面板不该永远驻留，
        用户下意识会点旁边空白处想退出。
      -->
      <div
        v-if="peek.isOpen"
        class="peek-mask"
        aria-hidden="true"
        @mousedown.self="peek.close()"
      ></div>
    </Transition>
    <Transition name="peek">
      <aside
        v-if="peek.isOpen"
        ref="rootRef"
        class="peek"
        :style="{ width: panelWidth + 'px' }"
        role="dialog"
        aria-modal="false"
        :aria-label="`文档预览：${peek.title}`"
        tabindex="-1"
      >
        <!-- 拖拽调宽 -->
        <div
          class="peek__grip"
          role="separator"
          aria-label="拖动调整面板宽度"
          aria-orientation="vertical"
          @pointerdown="onResizeStart"
          @pointermove="onResizeMove"
          @pointerup="onResizeEnd"
          @pointercancel="onResizeEnd"
        ></div>

        <!-- 头部 -->
        <header class="peek__head">
          <div class="peek__head-main">
            <div class="peek__badges">
              <span v-if="doc?.doc_type" class="peek__badge" :class="`peek__badge--${doc.doc_type}`">
                {{ doc.doc_type === 'weekly' ? '周复盘' : '日常' }}
              </span>
              <span v-else-if="memory" class="peek__badge peek__badge--memory">记忆</span>
              <span v-if="dateText" class="peek__date">{{ dateText }}</span>
            </div>

            <h2 class="peek__title">{{ peek.title }}</h2>
          </div>

          <button type="button" class="c-icon-btn" aria-label="关闭预览" @click="peek.close()">
            <AppIcon name="close" :size="16" />
          </button>
        </header>

        <!-- 元信息 -->
        <div v-if="topics.length || keywords.length || emotion" class="peek__meta">
          <span v-for="t in topics" :key="'t' + t" class="peek__chip peek__chip--topic">{{ t }}</span>
          <span v-for="k in keywords" :key="'k' + k" class="peek__chip peek__chip--kw">{{ k }}</span>
          <span v-if="emotion" class="peek__chip peek__chip--emo">{{ emotionText(emotion) }}</span>
        </div>

        <!-- 正文：可滚动，宽度足够阅读 -->
        <div ref="scrollRef" class="peek__body" @scroll="onScroll">
          <!-- 文档 · weekly 三段 -->
          <template v-if="doc && isWeekly">
            <section class="peek__section">
              <h3 class="peek__h3">problem · 问题</h3>
              <p class="peek__text">
                <HighlightText :text="doc.problem || '（未填写）'" :terms="peek.terms" />
              </p>
            </section>
            <section class="peek__section">
              <h3 class="peek__h3">analysis · 分析</h3>
              <p class="peek__text">
                <HighlightText :text="doc.analysis || '（未填写）'" :terms="peek.terms" />
              </p>
            </section>
            <section class="peek__section">
              <h3 class="peek__h3">solution · 方案</h3>
              <p class="peek__text">
                <HighlightText :text="doc.solution || '（未填写）'" :terms="peek.terms" />
              </p>
            </section>
          </template>

          <!-- 文档 · daily 正文 -->
          <template v-else-if="doc">
            <p class="peek__text">
              <HighlightText :text="doc.content || '（无内容）'" :terms="peek.terms" />
            </p>
          </template>

          <!-- 记忆 -->
          <template v-else-if="memory">
            <section class="peek__section">
              <h3 class="peek__h3">概要</h3>
              <p class="peek__text">
                <HighlightText :text="memory.summary || '（无摘要）'" :terms="peek.terms" />
              </p>
            </section>

            <section v-if="memory.insights?.length" class="peek__section">
              <h3 class="peek__h3">核心洞察</h3>
              <ul class="peek__list">
                <li v-for="(ins, i) in memory.insights" :key="i">{{ ins }}</li>
              </ul>
            </section>

            <section v-if="memory.dialogues?.length" class="peek__section">
              <h3 class="peek__h3">对话记录（{{ memory.dialogues.length }} 条）</h3>
              <div class="peek__dialogues">
                <div
                  v-for="(d, i) in memory.dialogues"
                  :key="i"
                  class="peek__dlg"
                  :class="`peek__dlg--${d.role === 'user' ? 'user' : 'assistant'}`"
                >
                  <span class="peek__dlg-role">{{ d.role === 'user' ? '我' : '咨询师' }}</span>
                  <p class="peek__dlg-text">{{ d.content }}</p>
                </div>
              </div>
            </section>

            <section v-if="memory.referenced_documents?.length" class="peek__section">
              <h3 class="peek__h3">引用文档</h3>
              <p class="peek__mono">{{ memory.referenced_documents.join('、') }}</p>
            </section>
          </template>

          <p v-if="sourcePath" class="peek__path">{{ sourcePath }}</p>
        </div>

        <!-- 底部动作 -->
        <footer class="peek__foot">
          <AppButton size="sm" variant="quiet" icon="copy" @click="onCopyAll">复制全文</AppButton>
          <AppButton size="sm" variant="quiet" icon="quote" @click="onCopySelection">
            复制选中
          </AppButton>
          <span class="peek__foot-spacer"></span>
          <AppButton size="sm" icon="pen" @click="onInsertToWeekly">摘入周记</AppButton>
          <AppButton size="sm" variant="primary" icon="chat" @click="onAskInChat">
            在对话中追问
          </AppButton>
        </footer>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.peek-mask {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-drawer) - 1);
  background: rgba(42, 35, 28, 0.12);
}

.peek {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: var(--z-drawer);
  display: flex;
  flex-direction: column;
  background: var(--surface-raised);
  border-left: 1px solid var(--border);
  box-shadow: var(--ef-3);
}

.peek:focus {
  outline: none;
}

/* ---------- 拖拽把手 ---------- */
.peek__grip {
  position: absolute;
  left: -3px;
  top: 0;
  bottom: 0;
  width: 7px;
  cursor: col-resize;
  z-index: 1;
}

.peek__grip::after {
  content: '';
  position: absolute;
  left: 3px;
  top: 50%;
  transform: translateY(-50%);
  width: 1px;
  height: 48px;
  background: var(--border-strong);
  opacity: 0;
  transition: opacity var(--dur-base) var(--ease-out);
}

.peek__grip:hover::after {
  opacity: 1;
}

/* ---------- 头部 ---------- */
.peek__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5) var(--sp-2);
  flex: 0 0 auto;
}

.peek__head-main {
  min-width: 0;
}

.peek__badges {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.peek__badge {
  padding: 1px 8px;
  border-radius: var(--r-sm);
  font-family: var(--font-mono);
  font-size: 11.5px;
}

.peek__badge--daily {
  background: rgba(78, 109, 106, 0.12);
  color: #3f5a57;
}

.peek__badge--weekly {
  background: var(--surface-warning-ghost);
  color: var(--warning);
}

.peek__badge--memory {
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
}

.peek__date {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-tertiary);
}

.peek__title {
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
  line-height: var(--lh-tight);
  color: var(--text-primary);
  word-break: break-word;
}

/* ---------- 元信息 ---------- */
.peek__meta {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  padding: 0 var(--sp-5) var(--sp-2);
  flex: 0 0 auto;
}

.peek__chip {
  padding: 1px 8px;
  border-radius: var(--r-pill);
  font-size: 12px;
}

.peek__chip--topic {
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
}

.peek__chip--kw {
  background: rgba(78, 109, 106, 0.1);
  color: #3f5a57;
}

.peek__chip--emo {
  background: var(--surface-warning-ghost);
  color: var(--warning);
}

/* ---------- 正文 ---------- */
.peek__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 var(--sp-5) var(--sp-5);
}

.peek__section + .peek__section {
  margin-top: var(--sp-5);
}

.peek__h3 {
  font-family: var(--font-sans);
  font-size: 12.5px;
  font-weight: var(--fw-medium);
  letter-spacing: 0.4px;
  color: var(--text-tertiary);
  margin-bottom: var(--sp-1);
}

/* 正文：这是阅读界面，字号与行宽都要够 */
.peek__text {
  font-size: 15.5px;
  line-height: 1.95;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.peek__list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding-left: 1.2em;
  list-style: disc;
}

.peek__list li {
  font-size: 15px;
  line-height: 1.85;
  color: var(--text-primary);
}

.peek__mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-tertiary);
  word-break: break-all;
}

.peek__path {
  margin-top: var(--sp-5);
  padding-top: var(--sp-3);
  border-top: 1px dashed var(--border-soft);
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-disabled);
  word-break: break-all;
}

/* ---------- 对话记录 ---------- */
.peek__dialogues {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.peek__dlg {
  max-width: 88%;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-md);
}

.peek__dlg--user {
  align-self: flex-end;
  background: var(--surface-inverse);
  color: var(--text-on-dark);
  -webkit-font-smoothing: antialiased;
}

.peek__dlg--assistant {
  align-self: flex-start;
  background: var(--surface-sunken);
}

.peek__dlg-role {
  display: block;
  font-size: 11px;
  opacity: 0.65;
  margin-bottom: 2px;
}

.peek__dlg-text {
  font-size: 14.5px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---------- 底部 ---------- */
.peek__foot {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  flex-wrap: wrap;
  padding: var(--sp-3) var(--sp-5) var(--sp-4);
  border-top: 1px solid var(--border-soft);
  flex: 0 0 auto;
}

.peek__foot-spacer {
  flex: 1;
}

/* ---------- 过渡 ---------- */
.peek-enter-active,
.peek-leave-active {
  transition: transform var(--dur-slow) var(--ease-out);
}

.peek-enter-from,
.peek-leave-to {
  transform: translateX(100%);
}

@media (max-width: 900px) {
  .peek {
    width: 100vw !important;
  }

  .peek__grip {
    display: none;
  }

  .peek__text {
    max-width: none;
  }
}
</style>
