import { reactive } from 'vue'

/**
 * Toast 状态。用模块级 reactive 而非 store：
 * 它不属于业务域状态，不需要跨会话持久化或 devtools 时间旅行。
 */

export type ToastType = 'ok' | 'err' | 'info'

export interface ToastItem {
  id: number
  message: string
  type: ToastType
  /** 可选动作按钮，如「立即预处理」 */
  action?: { label: string; handler: () => void }
}

let seq = 0
const items = reactive<ToastItem[]>([])
const timers = new Map<number, ReturnType<typeof setTimeout>>()

function dismiss(id: number) {
  const idx = items.findIndex((t) => t.id === id)
  if (idx >= 0) items.splice(idx, 1)
  const timer = timers.get(id)
  if (timer) {
    clearTimeout(timer)
    timers.delete(id)
  }
}

export function toast(
  message: string,
  type: ToastType = 'ok',
  duration = 2600,
  action?: ToastItem['action'],
) {
  const id = ++seq
  items.push({ id, message, type, action })

  // 带动作的提示停留更久，给用户反应时间
  const ttl = action ? Math.max(duration, 6000) : duration
  if (ttl > 0) {
    timers.set(
      id,
      setTimeout(() => dismiss(id), ttl),
    )
  }
  return id
}

export const toastOk = (m: string, d?: number, a?: ToastItem['action']) => toast(m, 'ok', d, a)
export const toastErr = (m: string, d?: number) => toast(m, 'err', d ?? 4000)
export const toastInfo = (m: string, d?: number, a?: ToastItem['action']) => toast(m, 'info', d, a)

export function useToast() {
  return { items, dismiss, toast, toastOk, toastErr, toastInfo }
}
