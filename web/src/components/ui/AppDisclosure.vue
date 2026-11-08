<script setup lang="ts">
import { ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'

/**
 * 统一的可展开区域。
 * 替换原项目里三套各写一遍的实现（result-card / rd-doc / rd-stage / trace-item）。
 */
const props = withDefaults(
  defineProps<{
    open?: boolean
    label: string
    /** 右侧次要信息：时间、计数等 */
    meta?: string
    /** false 时不可展开、不显示 caret */
    hasDetail?: boolean
    tone?: 'default' | 'error' | 'warn'
    /**
     * 容器形态：
     * - plain  裸条目（聊天执行链等消息附属信息，加框会喧宾夺主）
     * - line   左侧语义色条（日志类，高密度技术信息）
     * - card   卡片（记录类，每条是独立内容单元）
     */
    variant?: 'plain' | 'line' | 'card'
    /** 受控模式下由父组件管理展开状态 */
    controlled?: boolean
  }>(),
  { open: false, hasDetail: true, tone: 'default', controlled: false, variant: 'plain' },
)

const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const inner = ref(props.open)
const panelId = useId()

watch(
  () => props.open,
  (v) => {
    if (props.controlled) inner.value = v
  },
)

function toggle() {
  if (!props.hasDetail) return
  inner.value = !inner.value
  emit('update:open', inner.value)
}
</script>

<template>
  <div class="disc" :class="[`disc--${tone}`, `disc--v-${variant}`, inner && 'is-open']">
    <button
      v-if="hasDetail"
      type="button"
      class="disc__head"
      :aria-expanded="inner"
      :aria-controls="panelId"
      @click="toggle"
    >
      <AppIcon name="chevron-right" :size="13" class="disc__caret" />
      <span class="disc__label">{{ label }}</span>
      <span v-if="meta" class="disc__meta">{{ meta }}</span>
      <span class="disc__extra"><slot name="meta" /></span>
    </button>

    <div v-else class="disc__head disc__head--static">
      <span class="disc__label">{{ label }}</span>
      <span v-if="meta" class="disc__meta">{{ meta }}</span>
      <span class="disc__extra"><slot name="meta" /></span>
    </div>

    <!--
      常显预览区：不随折叠开合。
      用于结果卡这类「收起时也必须看到摘要」的场景 ——
      否则列表里只剩标题与日期，无法快速扫读。
    -->
    <div v-if="$slots.preview" class="disc__preview">
      <slot name="preview" />
    </div>

    <div v-show="hasDetail && inner" :id="panelId" class="disc__body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.disc {
  min-width: 0;
}

/* ---------- 容器形态 ---------- */

/* line：日志类，左侧语义色条帮助扫读高密度信息 */
.disc--v-line {
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-sm);
  border-left: 2px solid var(--border-strong);
  background: var(--surface);
}

.disc--v-line.disc--error {
  border-left-color: var(--danger);
  background: var(--surface-danger-ghost);
}

.disc--v-line.disc--warn {
  border-left-color: var(--warning);
}

/* card：记录类，每条是独立内容单元 */
.disc--v-card {
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-md);
  border: 1px solid var(--border-soft);
  background: var(--surface-raised);
  transition:
    border-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}

.disc--v-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--ef-1);
}

.disc__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: var(--sp-1) 0;
  text-align: left;
  color: var(--text-primary);
  border-radius: var(--r-sm);
}

.disc__head--static {
  cursor: default;
}

.disc__preview {
  padding: 2px 0 var(--sp-1) calc(13px + var(--sp-2));
}

.disc__caret {
  color: var(--text-tertiary);
  transition: transform var(--dur-base) var(--ease-out);
}

.disc.is-open .disc__caret {
  transform: rotate(90deg);
}

.disc__label {
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.disc__meta {
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
  white-space: nowrap;
}

.disc__extra {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-1);
}

.disc__body {
  padding: var(--sp-1) 0 var(--sp-2) calc(13px + var(--sp-2));
  color: var(--text-secondary);
}

.disc--error .disc__label {
  color: var(--danger);
}

.disc--warn .disc__label {
  color: var(--warning);
}
</style>
