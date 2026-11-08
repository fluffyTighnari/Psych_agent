<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import type { IconName } from './icon-names'

/**
 * 空状态统一载体。强制区分三态：
 *   loading  → 由父组件改用 AppSkeleton
 *   error    → 传 tone="error" 并提供 action（重试）
 *   empty    → 默认态，尽量给一个行动按钮
 *
 * 原项目把「加载失败」和「确实为空」显示成同一句话，用户无法判断该重试还是该去写点东西。
 */
withDefaults(
  defineProps<{
    icon?: IconName
    title: string
    desc?: string
    tone?: 'default' | 'error'
  }>(),
  { icon: 'info', tone: 'default' },
)
</script>

<template>
  <div class="empty" :class="`empty--${tone}`">
    <div class="empty__icon" aria-hidden="true">
      <AppIcon :name="icon" :size="22" />
    </div>
    <p class="empty__title">{{ title }}</p>
    <p v-if="desc" class="empty__desc">{{ desc }}</p>
    <div v-if="$slots.default" class="empty__actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  padding: var(--sp-7) var(--sp-4);
  text-align: center;
}

.empty__icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  margin-bottom: var(--sp-1);
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--surface-raised);
  color: var(--text-tertiary);
}

.empty--error .empty__icon {
  border-color: color-mix(in srgb, var(--danger) 35%, transparent);
  color: var(--danger);
}

.empty__title {
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
  color: var(--text-primary);
}

.empty__desc {
  font-size: var(--fs-sm);
  color: var(--text-tertiary);
  max-width: 42ch;
}

.empty__actions {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
}
</style>
