import { onBeforeUnmount, watch, type Ref } from 'vue'

/**
 * 浮层行为：焦点陷阱 + Esc 关闭 + body 滚动锁 + 关闭后焦点归还。
 * Modal / Drawer / Inspector 共用，避免每处各写一遍。
 */

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

let openCount = 0
let savedScrollY = 0

function lockScroll() {
  if (openCount++ > 0) return
  savedScrollY = window.scrollY
  document.body.style.overflow = 'hidden'
  document.body.style.position = 'fixed'
  document.body.style.top = `-${savedScrollY}px`
  document.body.style.width = '100%'
}

function unlockScroll() {
  if (--openCount > 0) return
  openCount = 0
  document.body.style.overflow = ''
  document.body.style.position = ''
  document.body.style.top = ''
  document.body.style.width = ''
  window.scrollTo(0, savedScrollY)
}

export interface OverlayOptions {
  open: Ref<boolean>
  containerRef: Ref<HTMLElement | null>
  onClose: () => void
}

export function useOverlay({ open, containerRef, onClose }: OverlayOptions) {
  let previouslyFocused: HTMLElement | null = null
  let locked = false

  function focusables(): HTMLElement[] {
    const root = containerRef.value
    if (!root) return []
    return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
      (el) => el.offsetParent !== null || el === document.activeElement,
    )
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation()
      onClose()
      return
    }

    if (e.key !== 'Tab') return

    // 焦点陷阱：Tab 在首尾之间循环，不逃逸到背景内容
    const list = focusables()
    if (list.length === 0) {
      e.preventDefault()
      return
    }
    const first = list[0]
    const last = list[list.length - 1]
    if (!first || !last) return

    const active = document.activeElement
    if (e.shiftKey && (active === first || !containerRef.value?.contains(active))) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && active === last) {
      e.preventDefault()
      first.focus()
    }
  }

  function activate() {
    previouslyFocused = document.activeElement as HTMLElement | null
    if (!locked) {
      lockScroll()
      locked = true
    }
    document.addEventListener('keydown', onKeydown, true)

    // 等 DOM 就位后把焦点移入浮层：优先 autofocus 元素，其次第一个可聚焦元素
    requestAnimationFrame(() => {
      const root = containerRef.value
      if (!root) return
      const auto = root.querySelector<HTMLElement>('[autofocus]')
      const target = auto ?? focusables()[0] ?? root
      target.focus()
    })
  }

  function deactivate() {
    document.removeEventListener('keydown', onKeydown, true)
    if (locked) {
      unlockScroll()
      locked = false
    }
    // 焦点归还给触发元素，键盘用户不会「掉」到页面顶部
    previouslyFocused?.focus?.()
    previouslyFocused = null
  }

  watch(
    open,
    (isOpen) => {
      if (isOpen) activate()
      else deactivate()
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    if (open.value) deactivate()
  })

  return { focusables }
}
