import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { Document, Memory } from '@/core/api/types'

/**
 * 文档预览（Peek）的全局状态。
 *
 * 放在 store 而不是某个组件内部，是因为它要服务四个入口：
 * 检索调试、聊天引用、记录页、图谱 Inspector。
 * 任何一处触发，页面级的 DocumentPeek 都会响应。
 */

export type PeekKind = 'document' | 'memory'

export interface PeekTarget {
  kind: PeekKind
  doc?: Document
  memory?: Memory
  /** 打开时的高亮词（来自检索/引用上下文） */
  terms?: string[]
}

/*
 * 默认宽度 50vw（1500px 屏 → 750px）。
 * 曾收窄到固定 620px，但用户反馈原比例更合适 —— 已改回。
 */
const MIN_WIDTH = 480
const MAX_WIDTH = 960
const DEFAULT_RATIO = 0.5

export const usePeekStore = defineStore('peek', () => {
  const target = ref<PeekTarget | null>(null)
  /** 面板宽度（px）；null 表示用默认比例 */
  const width = ref<number | null>(readStoredWidth())

  const isOpen = computed(() => target.value !== null)

  const title = computed(() => {
    const t = target.value
    if (!t) return ''
    if (t.kind === 'document') return t.doc?.title || t.doc?.doc_id || '文档'
    return t.memory?.title || '记忆'
  })

  const terms = computed(() => target.value?.terms ?? [])

  function openDocument(doc: Document, terms: string[] = []) {
    target.value = { kind: 'document', doc, terms }
  }

  function openMemory(memory: Memory, terms: string[] = []) {
    target.value = { kind: 'memory', memory, terms }
  }

  function close() {
    target.value = null
  }

  function setWidth(px: number) {
    const clamped = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Math.round(px)))
    width.value = clamped
    try {
      localStorage.setItem('psy:peek-width', String(clamped))
    } catch {
      // 隐私模式 / 配额满：宽度不持久化不影响使用
    }
  }

  /** 视口宽度对应的实际像素宽 */
  function resolvedWidth(viewportWidth: number): number {
    // 窄屏（<900px）铺满，不挤压内容
    if (viewportWidth < 900) return viewportWidth
    if (width.value !== null) {
      return Math.min(width.value, Math.max(MIN_WIDTH, viewportWidth * 0.72))
    }
    return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, viewportWidth * DEFAULT_RATIO))
  }

  return {
    target,
    width,
    isOpen,
    title,
    terms,
    openDocument,
    openMemory,
    close,
    setWidth,
    resolvedWidth,
  }
})

function readStoredWidth(): number | null {
  try {
    const raw = localStorage.getItem('psy:peek-width')
    if (!raw) return null
    const n = Number(raw)
    return Number.isFinite(n) ? n : null
  } catch {
    return null
  }
}
