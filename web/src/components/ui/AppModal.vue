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
  { width: '560px' },
)

const emit = defineEmits<{ close: [] }>()

const cardRef = ref<HTMLElement | null>(null)
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
  containerRef: cardRef,
  onClose: () => emit('close'),
})

function onMaskClick(e: MouseEvent) {
  // 只有点遮罩本身才关闭，点卡片内部不关
  if (e.target === e.currentTarget) emit('close')
}
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="modal-mask" @mousedown="onMaskClick">
        <div
          ref="cardRef"
          class="modal-card"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="title ? titleId : undefined"
          :style="{ width }"
          tabindex="-1"
        >
          <div v-if="title || $slots.head" class="modal-card__head">
            <slot name="head">
              <h3 :id="titleId" class="modal-card__title">{{ title }}</h3>
            </slot>
            <button
              type="button"
              class="c-icon-btn"
              aria-label="关闭"
              @click="emit('close')"
            >
              <AppIcon name="close" :size="16" />
            </button>
          </div>

          <div class="modal-card__body">
            <slot />
          </div>

          <div v-if="$slots.foot" class="modal-card__foot">
            <slot name="foot" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: grid;
  place-items: center;
  padding: var(--sp-5);
  background: rgba(42, 35, 28, 0.45);
  backdrop-filter: blur(2px);
}

.modal-card {
  display: flex;
  flex-direction: column;
  max-width: 100%;
  max-height: 82vh;
  border-radius: var(--r-lg);
  background: var(--surface-raised);
  box-shadow: var(--ef-3);
  overflow: hidden;
}

.modal-card:focus {
  outline: none;
}

.modal-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5) var(--sp-3);
  flex: 0 0 auto;
}

.modal-card__title {
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
}

.modal-card__body {
  padding: 0 var(--sp-5);
  overflow-y: auto;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  line-height: var(--lh-body);
}

.modal-card__foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2);
  padding: var(--sp-4) var(--sp-5) var(--sp-5);
  flex: 0 0 auto;
}

/* ---------- 过渡 ---------- */
.modal-enter-active,
.modal-leave-active {
  transition: opacity var(--dur-base) var(--ease-out);
}

.modal-enter-active .modal-card,
.modal-leave-active .modal-card {
  transition: transform var(--dur-base) var(--ease-out);
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-card,
.modal-leave-to .modal-card {
  transform: translateY(12px) scale(0.98);
}
</style>
