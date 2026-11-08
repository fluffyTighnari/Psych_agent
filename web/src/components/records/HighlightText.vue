<script setup lang="ts">
import { computed, h, type VNode } from 'vue'

/**
 * 命中高亮。
 *
 * 安全要点：**先切分文本，再逐段创建文本节点**，
 * 而不是「先拼 HTML 再塞 mark」——后者会让用户数据里的 < > 变成标签。
 * 这里全程 VNode，不经过 innerHTML。
 */

const props = withDefaults(
  defineProps<{
    text: string
    /** 需要高亮的片段（原文精确匹配） */
    terms?: string[]
    /** 最长保留长度，超出截断 */
    maxLen?: number
  }>(),
  { terms: () => [], maxLen: 0 },
)

const segments = computed<{ text: string; hit: boolean }[]>(() => {
  const raw = props.text ?? ''
  const text = props.maxLen > 0 && raw.length > props.maxLen ? raw.slice(0, props.maxLen) + '…' : raw

  const terms = [...new Set((props.terms ?? []).map((t) => t.trim()).filter(Boolean))]
  if (!terms.length) return [{ text, hit: false }]

  // 按长度降序，避免短词抢先匹配破坏长词
  terms.sort((a, b) => b.length - a.length)

  // 用正则一次性切分（转义特殊字符）
  const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const re = new RegExp(`(${escaped.join('|')})`, 'gi')

  const out: { text: string; hit: boolean }[] = []
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), hit: false })
    out.push({ text: m[0], hit: true })
    last = m.index + m[0].length
    // 零宽匹配保护
    if (m[0].length === 0) re.lastIndex++
  }
  if (last < text.length) out.push({ text: text.slice(last), hit: false })

  return out.length ? out : [{ text, hit: false }]
})

const tree = computed<VNode[]>(() =>
  segments.value.map((seg, i) =>
    seg.hit
      ? h('mark', { key: i, class: 'hl__mark' }, seg.text)
      : h('span', { key: i }, seg.text),
  ),
)
</script>

<template>
  <span class="hl"><component :is="() => tree" /></span>
</template>

<style scoped>
.hl {
  white-space: pre-wrap;
  word-break: break-word;
}

.hl :deep(.hl__mark) {
  padding: 0 1px;
  border-radius: 2px;
  background: color-mix(in srgb, var(--accent) 22%, transparent);
  color: var(--accent-deep);
  font-weight: var(--fw-medium);
}
</style>
