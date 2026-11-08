import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { connectionsApi, modelApi } from '@/core/api'
import type { ModelConfigMap, ModelConnection, ModelSlot, OllamaRunningModel } from '@/core/api/types'

export const MODEL_SLOTS: ModelSlot[] = ['small', 'large', 'chat']

export const SLOT_LABEL: Record<ModelSlot, string> = {
  small: '预处理 / 分类',
  large: '预处理 / 总结',
  chat: '路由 / 生成',
}

export const OLLAMA_PRESETS = ['qwen2:1.5b', 'qwen3.5:9b-128k', 'qwen3.6-27b', 'phi3-3.8b']
export const API_PRESETS = ['deepseek-v4-flash', 'deepseek-v4-pro', 'Qwen3.8-Max', 'Qwen3.7-Plus']

export function modelDisplayName(m: { driver: string; ollama_name?: string; api_model_name?: string }) {
  return m.driver === 'ollama' ? m.ollama_name || '—' : m.api_model_name || m.ollama_name || '—'
}

export const useModelsStore = defineStore('models', () => {
  /** 当前编辑中的配置 */
  const current = ref<ModelConfigMap | null>(null)
  /** 打开抽屉时的原始快照，用于判断哪些槽位被改动 */
  const original = ref<ModelConfigMap | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<string | null>(null)

  const ollamaModels = ref<string[]>([])
  const ollamaRunning = ref<OllamaRunningModel[]>([])
  /** 模型连接（ollama 与外部 API 统一形态） */
  const connections = ref<ModelConnection[]>([])

  const chips = computed(() => {
    if (!current.value) return []
    return MODEL_SLOTS.map((slot) => ({
      slot,
      name: modelDisplayName(current.value![slot]),
    }))
  })

  const isDirty = computed(() => {
    if (!current.value || !original.value) return false
    return JSON.stringify(current.value) !== JSON.stringify(original.value)
  })

  async function load(signal?: AbortSignal) {
    loading.value = true
    error.value = null
    try {
      const data = await modelApi.get({ signal })
      current.value = structuredClone(data)
      original.value = structuredClone(data)
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function save() {
    if (!current.value) return
    saving.value = true
    try {
      // api_key 是脱敏值，后端会识别并保留原值，这里原样回传即可
      await modelApi.update(current.value, { timeoutMs: 30000 })
      await load()
    } finally {
      saving.value = false
    }
  }

  async function loadOllamaList() {
    try {
      ollamaModels.value = (await modelApi.ollamaList()).models ?? []
    } catch {
      ollamaModels.value = []
    }
  }

  async function loadOllamaPs() {
    try {
      ollamaRunning.value = (await modelApi.ollamaPs()).models ?? []
    } catch {
      ollamaRunning.value = []
    }
  }

  /* ---------- 连接管理 ---------- */

  async function loadConnections() {
    try {
      const data = await connectionsApi.list()
      connections.value = data.connections ?? []
    } catch {
      // 连接列表拉取失败时退化为空列表，槽位仍可手填
      connections.value = []
    }
  }

  async function upsertConnection(conn: ModelConnection) {
    const res = await connectionsApi.upsert(conn)
    connections.value = res.connections ?? []
  }

  async function removeConnection(id: string) {
    await connectionsApi.remove(id)
    await loadConnections()
  }

  async function startOllama(modelName: string, keepAlive: string) {
    await modelApi.ollamaStart({ model_name: modelName, keep_alive: keepAlive }, { timeoutMs: 300000 })
    await loadOllamaPs()
  }

  /** 丢弃改动，回到打开抽屉时的快照 */
  function revert() {
    if (original.value) current.value = structuredClone(original.value)
  }

  return {
    current,
    original,
    loading,
    saving,
    error,
    ollamaModels,
    ollamaRunning,
    connections,
    chips,
    isDirty,
    load,
    save,
    loadOllamaList,
    loadOllamaPs,
    loadConnections,
    upsertConnection,
    removeConnection,
    startOllama,
    revert,
  }
})
