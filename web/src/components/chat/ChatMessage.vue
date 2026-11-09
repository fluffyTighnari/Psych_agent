<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import RichText from './RichText.vue'
import type { CitationContext } from '@/core/domain/citations'
import type { Turn } from '@/core/domain/turns'
import { toPlainText } from '@/core/domain/richtext'

/**
 * 单条消息。
 *
 * 结构（助手侧）：
 *   头像 · 名字
 *        └ 执行链（ExecutionChain，一行摘要，可展开）
 *        └ 气泡（RichText 渲染 Markdown-lite + 引用 chip）
 *        └ 操作栏
 *
 * 执行链放在头像下方而非气泡顶部，是为了让「怎么得出这个回答」和「回答本身」
 * 在视觉上分层：先看到过程摘要，再进入正文。
 */

const props = defineProps<{
  role: 'user' | 'assistant'
  speaker?: 'advisor' | 'guide'
  text: string
  streaming?: boolean
  citationCtx?: CitationContext
  showActions?: boolean
  /** 助手侧的 Turn（用于执行链） */
  turn?: Turn
}>()

const emit = defineEmits<{
  cite: [id: string]
  citeHover: [id: string | null]
  copy: []
  insertToWeekly: []
  /** 针对这条回复追问：把它作为引用附件挂到输入框 */
  replyTo: []
}>()

const hovered = ref(false)
const copied = ref(false)

const roleLabel = computed(() => {
  if (props.role === 'user') return '我'
  return props.speaker === 'guide' ? '引导者' : '建议者'
})

const avatarSrc = computed(() => {
  if (props.role === 'user') return `${import.meta.env.BASE_URL}avatars/user.png`
  const name = props.speaker === 'guide' ? 'guide' : 'advisor'
  return `${import.meta.env.BASE_URL}avatars/${name}.png`
})

const isInteractive = computed(() => props.role === 'assistant')

async function onCopy() {
  try {
    await navigator.clipboard.writeText(toPlainText(props.text))
    copied.value = true
    emit('copy')
    setTimeout(() => (copied.value = false), 1600)
  } catch {
    // 剪贴板不可用（非安全上下文）时静默失败，不打扰用户
  }
}
</script>

<template>
  <article
    class="msg"
    :class="[`msg--${role}`, speaker && `msg--${speaker}`]"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
  >
    <img class="msg__avatar" :src="avatarSrc" alt="" aria-hidden="true" />

    <div class="msg__main">
      <div class="msg__name">{{ roleLabel }}</div>

      <!-- 执行链：头像下方，气泡之上 -->
      <slot name="chain" />

      <div class="msg__bubble">
        <RichText
          :text="text"
          :streaming="streaming"
          :citation-ctx="citationCtx"
          :interactive="isInteractive"
          @cite="(id) => emit('cite', id)"
          @cite-hover="(id) => emit('citeHover', id)"
        />
      </div>

      <div v-if="showActions && !streaming" class="msg__actions" :class="{ 'is-visible': hovered }">
        <button type="button" class="msg__action" :title="copied ? '已复制' : '复制'" @click="onCopy">
          <AppIcon :name="copied ? 'check' : 'copy'" :size="13" />
          <span>{{ copied ? '已复制' : '复制' }}</span>
        </button>
        <button
          v-if="role === 'assistant'"
          type="button"
          class="msg__action"
          title="追问这条回复"
          @click="emit('replyTo')"
        >
          <AppIcon name="quote" :size="13" />
          <span>追问</span>
        </button>
        <button
          v-if="role === 'assistant'"
          type="button"
          class="msg__action"
          title="摘入周记"
          @click="emit('insertToWeekly')"
        >
          <AppIcon name="pen" :size="13" />
          <span>摘入周记</span>
        </button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.msg {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
}

.msg--user {
  flex-direction: row-reverse;
}

/* ---------- 头像 ---------- */
.msg__avatar {
  display: block;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: 50%;
  object-fit: cover;
  object-position: center;
  user-select: none;
  background: transparent;
}

/* ---------- 内容 ---------- */
.msg__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-width: 76%;
}

.msg--user .msg__main {
  align-items: flex-end;
}

.msg__name {
  font-size: var(--fs-2xs);
  letter-spacing: 0.4px;
  margin-bottom: 2px;
  color: var(--text-tertiary);
}

.msg--advisor .msg__name {
  color: var(--accent-deep);
}

.msg--guide .msg__name {
  color: var(--reason);
}

.msg__bubble {
  border-radius: var(--r-lg);
  font-size: var(--fs-base);
  padding: var(--sp-3) var(--sp-4);
}

/*
 * 用户气泡：淡黄纸块。
 *
 * 起初是近黑反白（太抢眼，每句话砸下一块黑），后来一度改成完全透明
 * （问题是连续几行时看不出哪里是自己的话）。
 * 这里是两者的中间点：淡黄、无阴影、边框几乎不可见 ——
 * 能认出气泡，但视觉重量明显低于建议者的白卡。
 */
.msg--user .msg__bubble {
  background: var(--surface-user);
  color: var(--text-primary);
  border: 1px solid var(--border-user);
  border-bottom-right-radius: var(--r-sm);
}

.msg--assistant .msg__bubble {
  background: var(--surface-raised);
  border: 1px solid var(--border-soft);
  border-bottom-left-radius: var(--r-sm);
  box-shadow: var(--ef-1);
}

.msg--guide .msg__bubble {
  border-color: color-mix(in srgb, var(--reason) 28%, var(--border-soft));
}

/* ---------- 操作栏 ---------- */
.msg__actions {
  display: flex;
  gap: var(--sp-1);
  margin-top: var(--sp-1);
  opacity: 0;
  transition: opacity var(--dur-base) var(--ease-out);
}

.msg__actions.is-visible {
  opacity: 1;
}

.msg__action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--r-sm);
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--fs-2xs);
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.msg__action:hover {
  background: var(--surface-sunken);
  color: var(--text-secondary);
}

@media (max-width: 720px) {
  .msg__main {
    max-width: 88%;
  }

  .msg__actions {
    opacity: 1;
  }
}
</style>
