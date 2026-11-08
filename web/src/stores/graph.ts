import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { dataApi, toolApi } from '@/core/api'
import type { GraphData, GraphNode } from '@/core/api/types'

/**
 * 图谱数据与交互焦点。
 *
 * 与 turn store 的分工：turn 只用 graphNodes 做引用解析；
 * 这里管理图谱视图自己的状态（选中节点、过滤、刷新）。
 */

export const useGraphStore = defineStore('graph', () => {
  const data = shallowRef<GraphData>({ nodes: [], links: [] })
  const loading = ref(false)
  const error = ref<string | null>(null)
  const selected = ref<GraphNode | null>(null)
  /** 由对话侧 hover 引用 chip 时设置，图谱据此高亮 */
  const externalFocusId = ref<string | null>(null)
  const summarizing = ref(false)

  const nodes = computed(() => data.value.nodes)
  const links = computed(() => data.value.links)
  const isEmpty = computed(() => nodes.value.length === 0)

  /** 各类型节点计数（图例与无障碍描述用） */
  const counts = computed(() => {
    const acc = { session: 0, memory: 0, document: 0, reason: 0 }
    for (const n of nodes.value) {
      if (n.type in acc) acc[n.type] += 1
    }
    return acc
  })

  /** 给屏幕阅读器的等价文本 */
  const a11ySummary = computed(() => {
    const c = counts.value
    const parts: string[] = []
    if (c.session) parts.push(`${c.session} 个会话`)
    if (c.memory) parts.push(`${c.memory} 条记忆`)
    if (c.document) parts.push(`${c.document} 篇文档`)
    if (c.reason) parts.push(`${c.reason} 步推理`)
    return parts.length ? `会话关联图谱：${parts.join('、')}` : '会话关联图谱：暂无数据'
  })

  async function load(signal?: AbortSignal) {
    loading.value = true
    error.value = null
    try {
      data.value = await dataApi.graph({ signal })
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function summarize() {
    summarizing.value = true
    try {
      const res = await toolApi.summarize({ timeoutMs: 180000 })
      await load()
      return res.summary_text
    } finally {
      summarizing.value = false
    }
  }

  function select(node: GraphNode | null) {
    selected.value = node
  }

  function setExternalFocus(id: string | null) {
    externalFocusId.value = id
  }

  /** 某节点的邻接节点（Inspector 用） */
  function neighborsOf(id: string): { id: string; name: string; type: GraphNode['type']; relation: string }[] {
    const byId = new Map(nodes.value.map((n) => [n.id, n]))
    const out: { id: string; name: string; type: GraphNode['type']; relation: string }[] = []
    for (const l of links.value) {
      if (l.source === id) {
        const t = byId.get(l.target)
        if (t) out.push({ id: t.id, name: t.name, type: t.type, relation: l.relation })
      } else if (l.target === id) {
        const s = byId.get(l.source)
        if (s) out.push({ id: s.id, name: s.name, type: s.type, relation: l.relation })
      }
    }
    return out
  }

  return {
    data,
    nodes,
    links,
    loading,
    error,
    selected,
    externalFocusId,
    summarizing,
    isEmpty,
    counts,
    a11ySummary,
    load,
    summarize,
    select,
    setExternalFocus,
    neighborsOf,
  }
})
