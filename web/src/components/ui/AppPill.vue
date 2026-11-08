<script setup lang="ts">
withDefaults(
  defineProps<{
    active?: boolean
    tone?: 'accent' | 'neutral'
    size?: 'sm' | 'md'
  }>(),
  { active: false, tone: 'accent', size: 'md' },
)
</script>

<template>
  <button
    type="button"
    class="pill"
    :class="[`pill--${tone}`, size === 'sm' && 'pill--sm', active && 'is-active']"
    :aria-pressed="active"
  >
    <slot />
  </button>
</template>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  padding: 6px 14px;
  border-radius: var(--r-pill);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--fs-xs);
  white-space: nowrap;
  cursor: pointer;
  transition:
    background var(--dur-base) var(--ease-out),
    border-color var(--dur-base) var(--ease-out),
    color var(--dur-base) var(--ease-out);
}

.pill--sm {
  padding: 4px 10px;
  font-size: var(--fs-2xs);
}

.pill:hover:not(.is-active) {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.pill--accent.is-active {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--text-on-accent);
}

.pill--neutral.is-active {
  background: var(--surface-inverse);
  border-color: var(--surface-inverse);
  color: var(--text-on-dark);
}
</style>
