<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 行数；card 变体下为卡片数 */
    lines?: number
    variant?: 'text' | 'card'
  }>(),
  { lines: 3, variant: 'text' },
)
</script>

<template>
  <div class="skeleton" :class="`skeleton--${variant}`" aria-hidden="true" role="presentation">
    <div v-for="i in lines" :key="i" class="skeleton__bar" :style="{ width: `${72 + ((i * 13) % 26)}%` }"></div>
  </div>
</template>

<style scoped>
.skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.skeleton--card {
  gap: var(--sp-3);
}

.skeleton--card .skeleton__bar {
  height: 68px;
  border-radius: var(--r-md);
}

.skeleton__bar {
  height: 11px;
  border-radius: var(--r-pill);
  background: linear-gradient(
    90deg,
    var(--surface-sunken) 0%,
    var(--surface-overlay) 50%,
    var(--surface-sunken) 100%
  );
  background-size: 200px 100%;
  animation: shimmer 1.4s ease-in-out infinite;
}
</style>
