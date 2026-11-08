<script setup lang="ts">
import AppButton from './AppButton.vue'
import AppModal from './AppModal.vue'

/**
 * 破坏性操作确认。
 * 替换原生 confirm()：原生弹窗与整站纸感视觉割裂，且无法表达
 * 「清空对话」与「重置会话」的语义差异（前者保留 session_id 与记忆库）。
 */
withDefaults(
  defineProps<{
    open: boolean
    title: string
    /** 说清后果，不要只写「确定吗」 */
    message: string
    confirmLabel?: string
    cancelLabel?: string
    /** 危险操作把确认按钮染红 */
    danger?: boolean
    loading?: boolean
  }>(),
  { confirmLabel: '确定', cancelLabel: '取消', danger: false, loading: false },
)

const emit = defineEmits<{ confirm: []; cancel: [] }>()
</script>

<template>
  <AppModal :open="open" :title="title" width="440px" @close="emit('cancel')">
    <p class="confirm__msg">{{ message }}</p>

    <template #foot>
      <AppButton variant="ghost" @click="emit('cancel')">{{ cancelLabel }}</AppButton>
      <AppButton
        :variant="danger ? 'danger' : 'primary'"
        :loading="loading"
        @click="emit('confirm')"
      >
        {{ confirmLabel }}
      </AppButton>
    </template>
  </AppModal>
</template>

<style scoped>
.confirm__msg {
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  color: var(--text-secondary);
  padding-bottom: var(--sp-2);
}
</style>
