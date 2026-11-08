import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { dataApi } from '@/core/api'
import type { TraceItem } from '@/core/api/types'

/**
 * 原始 trace 缓冲。
 * 与 chat 的 TurnTrace 分工：这里保留后端推送的全部原始日志（调试视图），
 * TurnTrace 只关心「当前这一轮」的语义化阶段。
 */
export const useTraceStore = defineStore('trace', () => {
  const logs = ref<TraceItem[]>([])
  const version = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** 去重签名：timestamp + stage + label + content */
  const seen = new Set<string>()

  function signature(t: TraceItem) {
    return `${t.timestamp}_${t.stage}_${t.label}_${JSON.stringify(t.content ?? {})}`
  }

  const count = computed(() => logs.value.length)

  function clear() {
    logs.value = []
    seen.clear()
  }

  function add(items: TraceItem[]) {
    let added = 0
    for (const item of items) {
      const sig = signature(item)
      if (seen.has(sig)) continue
      seen.add(sig)
      logs.value.push(item)
      added++
    }
    return added
  }

  async function loadAll(signal?: AbortSignal) {
    loading.value = true
    error.value = null
    try {
      const data = await dataApi.traceAll({ signal })
      clear()
      version.value = data.version ?? 0
      add(data.logs ?? [])
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  return { logs, version, loading, error, count, clear, add, loadAll }
})
