<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import type { IconName } from './icon-names'

withDefaults(
  defineProps<{
    variant?: 'primary' | 'ghost' | 'danger' | 'quiet'
    size?: 'sm' | 'md'
    disabled?: boolean
    loading?: boolean
    icon?: IconName
    /** 原生按钮类型 */
    type?: 'button' | 'submit'
  }>(),
  { variant: 'ghost', size: 'md', disabled: false, loading: false, type: 'button' },
)
</script>

<template>
  <button
    :type="type"
    class="c-btn"
    :class="[`c-btn--${variant}`, size === 'sm' && 'c-btn--sm', loading && 'is-loading']"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
  >
    <AppIcon v-if="icon && !loading" :name="icon" :size="size === 'sm' ? 14 : 16" />
    <slot />
  </button>
</template>
