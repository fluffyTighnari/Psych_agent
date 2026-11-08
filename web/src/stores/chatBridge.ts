import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 跨视图的「引用附件」通道。
 *
 * 场景：用户在记录页 / 文档预览里点「在对话中追问」，
 * 需要把一个文档作为附件带到主对话的输入框上方。
 * 这两个页面没有父子关系，用 store 做一次性传递最简单。
 *
 * 对话页挂载时取走（take），取走即清空，避免切回来又冒出来。
 */

export interface BridgeAttachment {
  id: string
  kind: 'document' | 'message'
  doc_id?: string
  title: string
  content: string
  role?: 'guide' | 'advisor'
}

export const useChatBridgeStore = defineStore('chatBridge', () => {
  const pending = ref<BridgeAttachment[]>([])

  /** 放入一个待附加的引用（可重复调用，自动去重） */
  function attach(a: BridgeAttachment) {
    if (pending.value.some((x) => x.id === a.id)) return
    pending.value = [...pending.value, a]
  }

  /** 取走全部待附加项并清空 */
  function take(): BridgeAttachment[] {
    const out = pending.value
    pending.value = []
    return out
  }

  function clear() {
    pending.value = []
  }

  return { pending, attach, take, clear }
})
