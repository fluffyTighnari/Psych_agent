<script setup lang="ts">
import { RouterView } from 'vue-router'
import AppRail from '@/components/layout/AppRail.vue'
import AppToast from '@/components/ui/AppToast.vue'
import DocumentPeek from '@/components/document/DocumentPeek.vue'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
</script>

<template>
  <div class="app-shell" :class="{ 'is-focus': ui.focusMode }">
    <!-- 专注模式下隐藏导航，让正文真正居中 -->
    <AppRail v-if="!ui.focusMode" />
    <main class="app-main">
      <RouterView v-slot="{ Component }">
        <Transition name="view" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>
    <!-- 页面级文档预览：四个入口共用，宽度与图谱等面板无关 -->
    <DocumentPeek />
    <AppToast />
  </div>
</template>

<style scoped>
.view-enter-active,
.view-leave-active {
  transition:
    opacity var(--dur-base) var(--ease-out),
    transform var(--dur-base) var(--ease-out);
}

.view-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.view-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
