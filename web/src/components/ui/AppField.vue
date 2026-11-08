<script setup lang="ts">
import { onMounted, onUpdated, ref, useId } from 'vue'

/**
 * 表单字段容器。
 *
 * 无障碍做法：挂载后自动把 label 的 id 关联到字段内的原生控件上。
 *
 * 为什么不要求使用方手写关联：
 * 之前的版本通过 slot 把 id 传给使用方，但实际没有任何一处绑定，
 * axe 扫出 8 处 critical「表单元素没有可访问名称」。
 * 项目里所有控件都带统一类名（c-input / c-select / c-textarea），
 * 因此在容器内自动查找并绑定，比依赖每个调用方自觉可靠得多。
 */

const props = withDefaults(
  defineProps<{
    label?: string
    hint?: string
    error?: string
    required?: boolean
    desc?: string
  }>(),
  { required: false },
)

const rawId = useId()
const labelId = `fld-${rawId}-label`
const descId = `fld-${rawId}-desc`
const errorId = `fld-${rawId}-err`

const rootRef = ref<HTMLElement | null>(null)

const CONTROL_SELECTOR = 'input, select, textarea'

function syncA11y() {
  const root = rootRef.value
  if (!root) return

  for (const el of root.querySelectorAll<HTMLElement>(CONTROL_SELECTOR)) {
    // 跳过嵌套字段自己的控件
    if (el.closest('.field') !== root) continue

    if (props.label && !el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby')) {
      el.setAttribute('aria-labelledby', labelId)
    }
    if (props.required) el.setAttribute('aria-required', 'true')

    if (props.error) {
      el.setAttribute('aria-describedby', errorId)
      el.setAttribute('aria-invalid', 'true')
    } else if ((props.hint || props.desc) && !el.hasAttribute('aria-describedby')) {
      el.setAttribute('aria-describedby', descId)
    }
  }
}

onMounted(syncA11y)
onUpdated(syncA11y)
</script>

<template>
  <div ref="rootRef" class="field" :class="{ 'has-error': !!error }">
    <span v-if="label" :id="labelId" class="field__label">
      {{ label }}
      <span v-if="required" class="field__req" aria-hidden="true">*</span>
    </span>

    <p v-if="desc" :id="descId" class="field__desc">{{ desc }}</p>

    <slot />

    <p v-if="error" :id="errorId" class="field__error" role="alert">{{ error }}</p>
    <p v-else-if="hint" :id="descId" class="field__hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.field__label {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  letter-spacing: 0.3px;
}

.field__req {
  color: var(--accent-deep);
}

.field__desc {
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
  line-height: var(--lh-tight);
}

.field__hint {
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

.field__error {
  font-size: var(--fs-2xs);
  color: var(--danger);
}

.has-error :deep(.c-input),
.has-error :deep(.c-select),
.has-error :deep(.c-textarea) {
  border-color: var(--danger);
}
</style>
