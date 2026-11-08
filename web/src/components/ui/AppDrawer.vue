<script setup lang="ts">
import { ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { useOverlay } from './useOverlay'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    /** 视觉宽度 */
    width?: string
  }>(),
  { width: '460px' },
)

const emit = defineEmits<{ close: [] }>()

const panelRef = ref<HTMLElement | null>(null)
const openRef = ref(props.open)
const titleId = useId()

watch(
  () => props.open,
  (v) => {
    openRef.value = v
  },
)

useOverlay({
  open: openRef,
  containerRef: panelRef,
  onClose: () => emit('close'),
})

function onMaskClick(e: MouseEvent) {
  if (e.target === e.currentTarget) emit('close')
}
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="open" class="drawer-root">
        <div class="drawer-mask" @mousedown="onMaskClick"></div>
        <aside
          ref="panelRef"
          class="drawer-panel"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="title ? titleId : undefined"
          :style="{ width }"
          tabindex="-1"
        >
          <header v-if="title || $slots.head" class="drawer-panel__head">
            <slot name="head">
              <h3 :id="titleId" class="drawer-panel__title">{{ title }}</h3>
            </slot>
            <button type="button" class="c-icon-btn" aria-label="关闭" @click="emit('close')">
              <AppIcon name="close" :size="16" />
            </button>
          </header>

          <div class="drawer-panel__body">
            <slot />
          </div>

          <footer v-if="$slots.foot" class="drawer-panel__foot">
            <slot name="foot" />
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer-root {
  position: fixed;
  inset: 0;
  z-index: var(--z-drawer);
}

.drawer-mask {
  position: absolute;
  inset: 0;
  background: rgba(42, 35, 28, 0.35);
}

.drawer-panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  max-width: 92vw;
  background: var(--surface-raised);
  border-left: 1px solid var(--border);
  box-shadow: var(--ef-3);
}

.drawer-panel:focus {
  outline: none;
}

.drawer-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-5) var(--sp-5) var(--sp-2);
  flex: 0 0 auto;
}

.drawer-panel__title {
  font-size: var(--fs-lg);
  font-weight: var(--fw-bold);
}

.drawer-panel__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 var(--sp-5) var(--sp-4);
}

.drawer-panel__foot {
  flex: 0 0 auto;
  padding: var(--sp-4) var(--sp-5) var(--sp-5);
  border-top: 1px solid var(--border-soft);
  background: var(--surface-raised);
}

/* ---------- 过渡 ---------- */
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity var(--dur-base) var(--ease-out);
}

.drawer-enter-active .drawer-panel,
.drawer-leave-active .drawer-panel {
  transition: transform var(--dur-slow) var(--ease-out);
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from .drawer-panel,
.drawer-leave-to .drawer-panel {
  transform: translateX(100%);
}
</style>
