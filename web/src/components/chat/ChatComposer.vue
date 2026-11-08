<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'

/**
 * 输入区。
 * 与旧版的差异：模式在首条后锁定（显示为状态条），guided 模式提供显式「结束并生成建议」，
 * 发送中可中止 —— 旧版完全没有中止能力，用户只能干等伪流式跑完。
 */

export interface ComposerAttachment {
  id: string
  kind: 'document' | 'message'
  doc_id?: string
  title: string
  content: string
  role?: 'guide' | 'advisor'
}

const props = defineProps<{
  sending: boolean
  mode: 'direct' | 'guided' | null
  modeLocked: boolean
  anchorProblem: string
  guidedPairCount: number
  /** 输入框上方的引用 chip（附上文档 / 追问某条回复） */
  attachments: ComposerAttachment[]
}>()

const emit = defineEmits<{
  send: [text: string, situation: string | null]
  abort: []
  endGuided: []
  'update:mode': [mode: 'direct' | 'guided']
  'remove-attachment': [id: string]
}>()

const text = ref('')
const situation = ref('')
const situationOpen = ref(false)
const inputRef = ref<HTMLTextAreaElement | null>(null)

const canSend = computed(() => text.value.trim().length > 0 && !props.sending)
const isGuided = computed(() => props.mode === 'guided')

/**
 * 引导链是否「已开始」。
 *
 * 只是选中了引导模式还没发第一条时，用户要做的是**说出自己的问题**，
 * 不是回答一个还不存在的提问。原先只看 mode，导致一选中就把输入框
 * 提示成「回答引导者的问题…」，语义错位。
 */
const guidedStarted = computed(() => isGuided.value && props.guidedPairCount > 0)
const showModePicker = computed(() => !props.modeLocked)

function autoGrow() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 240) + 'px'
}

watch(text, () => nextTick(autoGrow))

function submit() {
  if (!canSend.value) return
  const t = text.value.trim()
  const s = situation.value.trim() || null
  emit('send', t, s)
  text.value = ''
  situation.value = ''
  situationOpen.value = false
  nextTick(autoGrow)
}

function onKeydown(e: KeyboardEvent) {
  // Enter 发送 / Shift+Enter 换行（保持旧版习惯）
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}

function focusInput() {
  inputRef.value?.focus()
}

defineExpose({ focusInput })
</script>

<template>
  <div class="composer">
    <!-- 模式选择：仅首条前显示 -->
    <div v-if="showModePicker" class="mode-picker" role="group" aria-label="咨询模式">
      <button
        type="button"
        class="mode-card"
        :class="{ 'is-active': mode === 'direct' }"
        :aria-pressed="mode === 'direct'"
        @click="emit('update:mode', 'direct')"
      >
        <span class="mode-card__title">直接咨询</span>
        <span class="mode-card__desc">给我建议 / 总结</span>
      </button>
      <button
        type="button"
        class="mode-card"
        :class="{ 'is-active': mode === 'guided' }"
        :aria-pressed="mode === 'guided'"
        @click="emit('update:mode', 'guided')"
      >
        <span class="mode-card__title">引导咨询</span>
        <span class="mode-card__desc">逐步帮我推理，最后给出建议</span>
      </button>
    </div>

    <!-- 模式已锁定：显示状态条 -->
    <div v-else class="mode-locked">
      <span class="mode-locked__badge" :class="isGuided ? 'is-guided' : 'is-direct'">
        <AppIcon :name="isGuided ? 'route' : 'chat'" :size="12" />
        {{ isGuided ? '引导咨询' : '直接咨询' }}
      </span>

      <span v-if="isGuided && anchorProblem" class="mode-locked__anchor" :title="anchorProblem">
        {{ anchorProblem }}
      </span>
      <span v-if="isGuided" class="mode-locked__progress">第 {{ guidedPairCount + 1 }} 问</span>

      <AppButton
        v-if="isGuided && !sending"
        size="sm"
        variant="quiet"
        @click="emit('endGuided')"
      >
        结束并生成建议
      </AppButton>
    </div>

    <!-- 引用 chip：用户附上的文档 / 正在追问的那条回复 -->
    <div v-if="attachments.length" class="composer__chips">
      <span
        v-for="a in attachments"
        :key="a.id"
        class="composer__chip"
        :class="`composer__chip--${a.kind}`"
      >
        <AppIcon :name="a.kind === 'document' ? 'doc' : 'quote'" :size="11" />
        <span class="composer__chip-label">
          {{ a.kind === 'document' ? '附上' : '追问' }}
        </span>
        <span class="composer__chip-title" :title="a.title">{{ a.title }}</span>
        <button
          type="button"
          class="composer__chip-x"
          :aria-label="`移除引用：${a.title}`"
          @click="emit('remove-attachment', a.id)"
        >
          <AppIcon name="close" :size="10" />
        </button>
      </span>
    </div>

    <!-- 输入 -->
    <div class="composer__box">
      <textarea
        ref="inputRef"
        v-model="text"
        class="composer__input"
        rows="1"
        :placeholder="guidedStarted ? '回答引导者的问题…' : '说点什么…'"
        :disabled="sending"
        @keydown="onKeydown"
      ></textarea>

      <div class="composer__actions">
        <button
          v-if="!isGuided"
          type="button"
          class="composer__situation-toggle"
          :aria-expanded="situationOpen"
          @click="situationOpen = !situationOpen"
        >
          <AppIcon :name="situationOpen ? 'minus' : 'plus'" :size="12" />
          补充具体情境
        </button>

        <span class="composer__hint">Enter 发送 · Shift + Enter 换行</span>

        <AppButton
          v-if="sending"
          size="sm"
          variant="ghost"
          icon="stop"
          @click="emit('abort')"
        >
          停止
        </AppButton>
        <AppButton
          v-else
          variant="primary"
          size="sm"
          icon="send"
          :disabled="!canSend"
          @click="submit"
        >
          发送
        </AppButton>
      </div>
    </div>

    <!-- 情境输入 -->
    <textarea
      v-show="situationOpen && !isGuided"
      v-model="situation"
      class="composer__situation"
      rows="2"
      placeholder="补充真实的问题情境，让建议更可执行…（可选）"
    ></textarea>
  </div>
</template>

<style scoped>
.composer {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding-top: var(--sp-3);
}

/* ---------- 模式选择 ---------- */
.mode-picker {
  display: flex;
  gap: var(--sp-2);
}

.mode-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  background: var(--surface-raised);
  text-align: left;
  cursor: pointer;
  transition:
    border-color var(--dur-base) var(--ease-out),
    box-shadow var(--dur-base) var(--ease-out);
}

.mode-card:hover {
  border-color: var(--border-strong);
}

.mode-card.is-active {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--surface-accent-ghost);
}

.mode-card__title {
  font-family: var(--font-serif);
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  color: var(--text-primary);
}

.mode-card:nth-child(2).is-active {
  border-color: var(--reason);
  box-shadow: 0 0 0 3px var(--surface-reason-ghost);
}

.mode-card:nth-child(2).is-active .mode-card__title {
  color: var(--reason);
}

.mode-card__desc {
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

/* ---------- 锁定状态条 ---------- */
.mode-locked {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  padding: 5px var(--sp-2);
  border-radius: var(--r-md);
  background: var(--surface-sunken);
}

.mode-locked__badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border-radius: var(--r-pill);
  font-size: var(--fs-2xs);
  font-weight: var(--fw-medium);
}

.mode-locked__badge.is-guided {
  background: var(--surface-reason-ghost);
  color: var(--reason);
}

.mode-locked__badge.is-direct {
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
}

.mode-locked__anchor {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-2xs);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mode-locked__progress {
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

/* ---------- 引用 chip ---------- */
.composer__chips {
  display: flex;
  gap: var(--sp-1);
  flex-wrap: wrap;
}

.composer__chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 320px;
  padding: 3px 6px 3px 9px;
  border-radius: var(--r-pill);
  border: 1px solid var(--border);
  background: var(--surface);
  font-size: var(--fs-2xs);
  color: var(--text-secondary);
}

.composer__chip--document {
  border-color: color-mix(in srgb, var(--entity-document) 35%, var(--border));
}

.composer__chip--message {
  border-color: color-mix(in srgb, var(--reason) 35%, var(--border));
}

.composer__chip-label {
  color: var(--text-tertiary);
  white-space: nowrap;
}

.composer__chip-title {
  font-weight: var(--fw-medium);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer__chip-x {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.composer__chip-x:hover {
  background: var(--surface-sunken);
  color: var(--text-primary);
}

/* ---------- 输入框 ---------- */
.composer__box {
  display: flex;
  flex-direction: column;
  border-radius: var(--r-lg);
  border: 1px solid var(--border);
  background: var(--surface-raised);
  transition:
    border-color var(--dur-base) var(--ease-out),
    box-shadow var(--dur-base) var(--ease-out);
}

/*
 * 聚焦：淡朱砂边框（无外扩阴影）。
 *
 * 早先看着"抢眼"的真正原因是全局 :focus-visible 的焦点环叠在上面，
 * 两条描边同时出现才显得突兀。焦点环已对输入类元素豁免，
 * 现在这一圈淡红是唯一的焦点提示，既明确又不喧宾。
 */
.composer__box:focus-within {
  border-color: var(--accent-soft);
}

.composer__input {
  width: 100%;
  resize: none;
  border: none;
  background: transparent;
  padding: var(--sp-3) var(--sp-4) var(--sp-1);
  font-family: var(--font-sans);
  font-size: var(--fs-base);
  line-height: var(--lh-body);
  color: var(--text-primary);
  max-height: 240px;
}

.composer__input:focus {
  outline: none;
}

.composer__input::placeholder {
  color: var(--text-tertiary);
}

.composer__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-1) var(--sp-3) var(--sp-2);
}

.composer__situation-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--accent-deep);
  font-size: var(--fs-2xs);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: var(--r-sm);
}

.composer__situation-toggle:hover {
  background: var(--surface-accent-ghost);
}

.composer__hint {
  margin-left: auto;
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

.composer__situation {
  width: 100%;
  resize: vertical;
  min-height: 48px;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  background: var(--surface-raised);
  font-family: var(--font-sans);
  font-size: var(--fs-xs);
  color: var(--text-primary);
}

.composer__situation:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--surface-accent-ghost);
}

@media (max-width: 720px) {
  .composer__hint {
    display: none;
  }
}
</style>
