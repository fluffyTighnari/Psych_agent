import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 全局 UI 状态：导航折叠、连接状态、专注模式。
 *
 * 专注模式放在这里（而非 WriteView 局部）是因为它需要影响 App 外壳
 * ——隐藏左侧导航栏。局部状态无法跨越组件边界。
 */
export const useUiStore = defineStore('ui', () => {
  const railCollapsed = ref(false)
  const backendOnline = ref<boolean | null>(null)
  const sessionId = ref('')

  /** 写作专注模式：隐藏导航与视图头部，正文单栏居中 */
  const focusMode = ref(false)

  function toggleRail() {
    railCollapsed.value = !railCollapsed.value
  }

  function setFocusMode(on: boolean) {
    focusMode.value = on
  }

  function setBackendStatus(online: boolean) {
    backendOnline.value = online
  }

  function setSessionId(id: string) {
    sessionId.value = id
  }

  return {
    railCollapsed,
    backendOnline,
    sessionId,
    focusMode,
    toggleRail,
    setFocusMode,
    setBackendStatus,
    setSessionId,
  }
})
