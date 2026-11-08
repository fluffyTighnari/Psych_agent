<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const props = defineProps<{
  /** 覆盖路由 meta 里的标题 */
  title?: string
  /** 覆盖路由 meta 里的副标题 */
  sub?: string
}>()

const route = useRoute()
const resolvedTitle = computed(() => props.title ?? (route.meta.title as string) ?? '')
const resolvedSub = computed(() => props.sub ?? (route.meta.sub as string) ?? '')
</script>

<template>
  <header class="view-head">
    <div class="view-head__title">
      <h2>{{ resolvedTitle }}</h2>
      <p v-if="resolvedSub" class="view-head__sub">{{ resolvedSub }}</p>
    </div>
    <div class="view-head__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.view-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--sp-5);
  flex-wrap: wrap;
  padding-bottom: var(--sp-4);
  border-bottom: 1px solid var(--border);
  flex: 0 0 auto;
}

.view-head__title h2 {
  font-size: var(--fs-lg);
  font-weight: var(--fw-bold);
  letter-spacing: 1px;
}

.view-head__sub {
  margin-top: 2px;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.view-head__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.view-head__actions:empty {
  display: none;
}
</style>
