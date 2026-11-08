import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { sessionApi } from '@/core/api'
import type { ChatMode, SessionState } from '@/core/api/types'
import { useUiStore } from './ui'

/**
 * 当前会话（后端是全局单会话，current_session 表 id=1）。
 * 这里只做「后端状态的本地镜像」+ 派生视图，不做业务决策。
 */
export const useSessionStore = defineStore('session', () => {
  const ui = useUiStore()

  const state = ref<SessionState | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const sessionId = computed(() => state.value?.session_id ?? '')
  const mode = computed<ChatMode>(() => state.value?.mode ?? '')
  const guidedEnded = computed(() => state.value?.guided_ended ?? false)
  const problem = computed(() => state.value?.mode_problem ?? '')
  const history = computed(() => state.value?.full_chat_history ?? [])
  const guidedReasons = computed(() => state.value?.guided_reasons ?? [])
  const referencedDocIds = computed(() => state.value?.referenced_doc_ids ?? [])

  /** 引导链已完成的问答对数 */
  const guidedPairCount = computed(() => Math.floor(guidedReasons.value.length / 2))

  const isEmpty = computed(
    () => history.value.length === 0 && guidedReasons.value.length === 0,
  )

  async function load(signal?: AbortSignal) {
    loading.value = true
    error.value = null
    try {
      state.value = await sessionApi.state({ signal })
      ui.setBackendStatus(true)
      ui.setSessionId(state.value.session_id)
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : String(e)
      ui.setBackendStatus(false)
    } finally {
      loading.value = false
    }
  }

  async function clear(signal?: AbortSignal) {
    await sessionApi.clear({ signal })
    await load(signal)
  }

  async function reset(signal?: AbortSignal) {
    await sessionApi.reset({ signal })
    ui.setSessionId('')
    await load(signal)
  }

  /** 本地乐观更新：发送一条消息后立即反映到 history，避免整页重载 */
  function appendLocal(item: SessionState['full_chat_history'][number]) {
    if (!state.value) return
    state.value.full_chat_history.push(item)
  }

  return {
    state,
    loading,
    error,
    sessionId,
    mode,
    guidedEnded,
    problem,
    history,
    guidedReasons,
    referencedDocIds,
    guidedPairCount,
    isEmpty,
    load,
    clear,
    reset,
    appendLocal,
  }
})
