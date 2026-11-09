<script setup lang="ts">
import { computed, h, type VNode } from 'vue'
import CitationChip from '@/components/chat/CitationChip.vue'
import {
  parseBlocks,
  type BlockNode,
  type InlineNode,
} from '@/core/domain/richtext'
import type { Citation, CitationContext } from '@/core/domain/citations'
import { extractCitations, stripSentinels } from '@/core/domain/citations'

/**
 * 富文本渲染。
 *
 * 输出 VNode 而非 HTML 字符串 —— **不经过 innerHTML / v-html**，
 * 所有文本都作为文本节点渲染，模型输出里的 `<script>` 只会被当成字面量。
 * 这是相比 markdown-it + v-html 的核心安全优势。
 */

const props = defineProps<{
  text: string
  streaming?: boolean
  citationCtx?: CitationContext
  /** 是否渲染引用 chip（用户消息不需要） */
  interactive?: boolean
}>()

const emit = defineEmits<{
  cite: [id: string]
  citeHover: [id: string | null]
}>()

/*
 * 渲染前先剥离工具哨兵（【心理咨询回复】等）。
 * 后端 parse_tool_result 已剥离，但历史落库数据与旧会话仍带前缀，
 * 不在这里处理就会直接显示给用户。
 */
const cleanText = computed(() => stripSentinels(props.text))

const blocks = computed<BlockNode[]>(() => parseBlocks(cleanText.value, !props.streaming))

/** 引用序号映射：同一 ID 全文复用同号 */
const citationMap = computed<Map<string, Citation>>(() => {
  if (!props.citationCtx) return new Map()
  return extractCitations(cleanText.value, props.citationCtx)
})

function citationFor(id: string): Citation {
  return (
    citationMap.value.get(id) ?? { id, kind: 'unknown', index: 0, title: id }
  )
}

/* ---------- 行内节点 → VNode ---------- */

function renderInline(nodes: InlineNode[]): VNode[] {
  return nodes.map((n, i) => {
    switch (n.type) {
      case 'text':
        return h('span', { key: i, class: 'rt__text' }, n.value)

      case 'strong':
        return h('strong', { key: i, class: 'rt__strong' }, renderInline(n.children))

      case 'em':
        return h('em', { key: i, class: 'rt__em' }, renderInline(n.children))

      case 'code':
        return h('code', { key: i, class: 'rt__code' }, n.value)

      // 「」：换衬线字体，呼应纸感排版，用于强调关键短语
      case 'quote':
        return h('q', { key: i, class: 'rt__quote' }, renderInline(n.children))

      case 'cite':
      case 'guide': {
        if (!props.interactive) {
          // 非交互场景（用户消息）直接丢弃标记，不显示残骸
          return null
        }
        const c = citationFor(n.id)
        return h(CitationChip, {
          key: i,
          citation: c,
          index: c.index,
          onSelect: (id: string) => emit('cite', id),
          onMouseenter: () => emit('citeHover', n.id),
          onMouseleave: () => emit('citeHover', null),
        })
      }

      default:
        return null
    }
  }).filter((v): v is VNode => v !== null)
}

/* ---------- 块级节点 → VNode ---------- */

function renderBlocks(list: BlockNode[]): VNode[] {
  return list.map((b, i) => {
    switch (b.type) {
      case 'paragraph': {
        const atEnd = i === list.length - 1
        const children = renderInline(b.children)
        if (props.streaming && atEnd) {
          children.push(h('span', { key: 'cursor', class: 'rt__cursor', 'aria-hidden': 'true' }))
        }
        return h('p', { key: i, class: 'rt__p' }, children)
      }

      case 'heading':
        return h(
          `h${Math.min(b.level + 3, 6)}`,
          { key: i, class: ['rt__h', `rt__h--${b.level}`] },
          renderInline(b.children),
        )

      case 'list':
        return h(
          b.ordered ? 'ol' : 'ul',
          { key: i, class: ['rt__list', b.ordered ? 'rt__list--ol' : 'rt__list--ul'] },
          b.items.map((item, j) => h('li', { key: j, class: 'rt__li' }, renderInline(item))),
        )

      case 'blockquote':
        return h('blockquote', { key: i, class: 'rt__bq' }, renderInline(b.children))

      case 'codeblock':
        return h(
          'pre',
          { key: i, class: 'rt__pre' },
          h('code', { class: 'rt__pre-code' }, b.value),
        )

      default:
        return null
    }
  }).filter((v): v is VNode => v !== null)
}

const tree = computed(() => renderBlocks(blocks.value))
</script>

<template>
  <div class="rt">
    <component :is="() => tree" />
  </div>
</template>

<style scoped>
.rt {
  line-height: var(--lh-loose);
  word-break: break-word;
}

/* ---------- 段落 ---------- */
.rt :deep(.rt__p) {
  margin: 0 0 0.7em;
  white-space: pre-wrap;
}

.rt :deep(.rt__p:last-child) {
  margin-bottom: 0;
}

/* ---------- 强调 ---------- */
.rt :deep(.rt__strong) {
  font-weight: var(--fw-bold);
  color: var(--text-primary);
}

.rt :deep(.rt__em) {
  font-style: italic;
}

/* 「」包裹：换衬线字体 + 轻微强调色，用于关键短语 */
.rt :deep(.rt__quote) {
  font-family: var(--font-serif);
  font-weight: var(--fw-medium);
  font-style: normal;
  color: var(--accent-deep);
  quotes: none;
}

.rt :deep(.rt__quote)::before,
.rt :deep(.rt__quote)::after {
  content: none;
}

.rt :deep(.rt__code) {
  padding: 1px 5px;
  border-radius: var(--r-sm);
  background: var(--surface-sunken);
  font-family: var(--font-mono);
  font-size: 0.9em;
  color: var(--accent-deep);
}

/* ---------- 标题 ---------- */
.rt :deep(.rt__h) {
  font-family: var(--font-serif);
  font-weight: var(--fw-bold);
  line-height: var(--lh-tight);
  margin: 1em 0 0.45em;
  color: var(--text-primary);
}

.rt :deep(.rt__h--1) {
  font-size: 1.18em;
}

.rt :deep(.rt__h--2) {
  font-size: 1.1em;
}

.rt :deep(.rt__h--3),
.rt :deep(.rt__h--4) {
  font-size: 1em;
}

.rt :deep(.rt__h:first-child) {
  margin-top: 0;
}

/* ---------- 列表 ---------- */
.rt :deep(.rt__list) {
  margin: 0.3em 0 0.8em;
  padding-left: 1.35em;
}

.rt :deep(.rt__list--ul) {
  list-style: none;
}

.rt :deep(.rt__list--ul .rt__li) {
  position: relative;
}

/* 无序列表用朱砂小点，与纸感气质一致（而非通用圆点） */
.rt :deep(.rt__list--ul .rt__li)::before {
  content: '';
  position: absolute;
  left: -0.95em;
  top: 0.72em;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.6;
}

.rt :deep(.rt__list--ol) {
  list-style: decimal;
}

.rt :deep(.rt__li) {
  margin-bottom: 0.3em;
  padding-left: 0.1em;
}

.rt :deep(.rt__li::marker) {
  color: var(--accent-deep);
  font-family: var(--font-mono);
  font-size: 0.88em;
}

/* ---------- 引用块 ---------- */
.rt :deep(.rt__bq) {
  margin: 0.6em 0;
  padding: 0.15em 0 0.15em 0.9em;
  border-left: 3px solid var(--accent-soft);
  color: var(--text-secondary);
  font-style: normal;
}

/* ---------- 代码块 ---------- */
.rt :deep(.rt__pre) {
  margin: 0.6em 0 0.8em;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-sm);
  background: var(--surface);
  border: 1px solid var(--border-soft);
  overflow-x: auto;
}

.rt :deep(.rt__pre-code) {
  font-family: var(--font-mono);
  font-size: 0.86em;
  line-height: var(--lh-body);
  color: var(--text-secondary);
  white-space: pre;
}

/* ---------- 流式光标 ---------- */
.rt :deep(.rt__cursor) {
  display: inline-block;
  width: 2px;
  height: 1.05em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--accent);
  animation: rt-blink 1s steps(2) infinite;
}

@keyframes rt-blink {
  50% {
    opacity: 0;
  }
}

/*
 * 用户气泡与页面同底后，不再需要任何按说话人区分的富文本配色 ——
 * 双方正文都是纸上的墨，统一走默认令牌。
 * 这里曾有三轮为"深底 → 沉纸底"调过的反向/半透明配色，已全部移除。
 */
</style>
