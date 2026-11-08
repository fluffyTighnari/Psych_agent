<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { useToast } from './useToast'
import type { IconName } from './icon-names'

const { items, dismiss } = useToast()

const iconMap: Record<string, IconName> = {
  ok: 'check',
  err: 'alert',
  info: 'info',
}
</script>

<template>
  <div class="toasts" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="t in items" :key="t.id" class="toast" :class="`toast--${t.type}`">
        <AppIcon :name="iconMap[t.type] ?? 'info'" :size="16" />
        <span class="toast__msg">{{ t.message }}</span>
        <button
          v-if="t.action"
          type="button"
          class="toast__action"
          @click="(t.action.handler(), dismiss(t.id))"
        >
          {{ t.action.label }}
        </button>
        <button type="button" class="toast__close" aria-label="关闭提示" @click="dismiss(t.id)">
          <AppIcon name="close" :size="13" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  bottom: var(--sp-5);
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--z-toast);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-2);
  pointer-events: none;
  max-width: min(560px, calc(100vw - 32px));
}

.toast {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 10px 12px 10px 16px;
  border-radius: var(--r-md);
  background: var(--surface-inverse);
  color: var(--text-on-dark);
  font-size: var(--fs-sm);
  box-shadow: var(--ef-3);
  pointer-events: auto;
  max-width: 100%;
}

.toast--err {
  background: var(--danger);
}

.toast--info {
  background: var(--entity-document);
}

.toast__msg {
  white-space: pre-wrap;
  word-break: break-word;
}

.toast__action {
  flex: 0 0 auto;
  margin-left: var(--sp-1);
  padding: 3px 10px;
  border-radius: var(--r-pill);
  background: rgba(255, 255, 255, 0.16);
  color: inherit;
  font-size: var(--fs-xs);
  font-weight: var(--fw-medium);
  transition: background var(--dur-fast) var(--ease-out);
}

.toast__action:hover {
  background: rgba(255, 255, 255, 0.26);
}

.toast__close {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: var(--r-sm);
  color: inherit;
  opacity: 0.6;
  transition: opacity var(--dur-fast) var(--ease-out);
}

.toast__close:hover {
  opacity: 1;
}

/* ---------- 进出场 ---------- */
.toast-enter-active,
.toast-leave-active {
  transition:
    opacity var(--dur-base) var(--ease-out),
    transform var(--dur-base) var(--ease-out);
}

.toast-enter-from {
  opacity: 0;
  transform: translateY(10px) scale(0.98);
}

.toast-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.98);
}
</style>
