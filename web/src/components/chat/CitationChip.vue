<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { KIND_ICON, KIND_LABEL, type Citation } from '@/core/domain/citations'

const props = defineProps<{
  citation: Citation
  /** 渲染为角标时的序号 */
  index: number
}>()

const emit = defineEmits<{ select: [id: string] }>()

const title = computed(() => `${KIND_LABEL[props.citation.kind]}${props.index} · ${props.citation.title}`)
</script>

<template>
  <button
    type="button"
    class="cite"
    :class="`cite--${citation.kind}`"
    :title="title"
    :aria-label="title"
    @click="emit('select', citation.id)"
    @mouseenter="emit('select', citation.id)"
  >
    <AppIcon :name="KIND_ICON[citation.kind]" :size="10" />
    <span class="cite__n">{{ index }}</span>
  </button>
</template>

<style scoped>
.cite {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin: 0 1px;
  padding: 1px 5px 1px 4px;
  border-radius: var(--r-sm);
  font-family: var(--font-mono);
  font-size: 9.5px;
  line-height: 1.5;
  vertical-align: super;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

.cite:hover {
  transform: translateY(-1px);
}

/* 类型色：文档=墨绿，记忆=黄铜，推理=紫 */
.cite--document {
  background: rgba(78, 109, 106, 0.14);
  color: #3f5a57;
}

.cite--document:hover {
  background: var(--entity-document);
  color: var(--text-on-dark);
}

.cite--memory {
  background: var(--surface-warning-ghost);
  color: var(--warning);
}

.cite--memory:hover {
  background: var(--entity-memory);
  color: var(--text-on-dark);
}

.cite--reason {
  background: var(--surface-reason-ghost);
  color: var(--reason);
}

.cite--reason:hover {
  background: var(--reason);
  color: var(--text-on-dark);
}

.cite--unknown {
  background: var(--surface-sunken);
  color: var(--text-secondary);
}

.cite--unknown:hover {
  background: var(--surface-inverse);
  color: var(--text-on-dark);
}

.cite__n {
  font-weight: var(--fw-medium);
}
</style>
