<script setup lang="ts">
import { computed } from 'vue'
import type { IconName } from './icon-names'

/**
 * 图标统一入口。引用 src/assets/icons.svg 里的 <symbol>，
 * 用 <use> 复用，保证全站 stroke 粗细、圆角、基线一致。
 */
const props = withDefaults(
  defineProps<{
    name: IconName
    size?: number | string
    /** 仅图标无文字时必填，作为无障碍名称 */
    label?: string
  }>(),
  { size: 18 },
)

const px = computed(() => (typeof props.size === 'number' ? `${props.size}px` : props.size))
const href = computed(() => `#i-${props.name}`)
</script>

<template>
  <svg
    class="app-icon"
    :style="{ width: px, height: px }"
    :aria-hidden="label ? undefined : 'true'"
    :aria-label="label"
    :role="label ? 'img' : undefined"
    focusable="false"
  >
    <use :href="href" />
  </svg>
</template>

<style scoped>
.app-icon {
  flex: 0 0 auto;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  overflow: visible;
}
</style>
