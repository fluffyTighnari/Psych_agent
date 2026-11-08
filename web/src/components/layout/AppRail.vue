<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const ui = useUiStore()
const brandMark = `${import.meta.env.BASE_URL}brand/xinji-mark-transparent-128.png`

const items = [
  { name: 'chat', label: '主对话', en: 'Chat', icon: 'chat' },
  { name: 'records', label: '过往记录', en: 'Archive', icon: 'archive' },
  { name: 'write', label: '码字编辑', en: 'Compose', icon: 'pen' },
  { name: 'trace', label: '流程日志', en: 'Trace', icon: 'pulse' },
  { name: 'retrieval', label: '检索调试', en: 'Retrieval', icon: 'search' },
] as const

const currentName = computed(() => (route.name as string) ?? 'chat')

const connState = computed(() => {
  if (ui.backendOnline === null) return { cls: '', text: '连接中…' }
  return ui.backendOnline
    ? { cls: 'is-on', text: '后端已连接' }
    : { cls: 'is-off', text: '后端未连接' }
})
</script>

<template>
  <aside class="rail" :class="{ 'is-collapsed': ui.railCollapsed }">
    <div class="rail__brand">
      <div class="rail__seal" aria-hidden="true">
        <img :src="brandMark" alt="" />
      </div>
      <div class="rail__brand-text">
        <h1>心迹</h1>
        <span>Psych Journal</span>
      </div>
    </div>

    <nav class="rail__nav" aria-label="主导航">
      <RouterLink
        v-for="item in items"
        :key="item.name"
        :to="{ name: item.name }"
        class="rail__item"
        :class="{ 'is-active': currentName === item.name }"
        :aria-current="currentName === item.name ? 'page' : undefined"
        :title="ui.railCollapsed ? item.label : undefined"
      >
        <AppIcon :name="item.icon" :size="19" />
        <span class="rail__label">{{ item.label }}</span>
        <i class="rail__en">{{ item.en }}</i>
      </RouterLink>
    </nav>

    <div class="rail__footer">
      <div class="rail__conn" role="status" aria-live="polite">
        <span class="rail__dot" :class="connState.cls" aria-hidden="true"></span>
        <span class="rail__conn-text">{{ connState.text }}</span>
      </div>
      <div v-if="ui.sessionId" class="rail__session" :title="ui.sessionId">
        session · {{ ui.sessionId }}
      </div>
    </div>
  </aside>
</template>

<style scoped>
.rail {
  flex: 0 0 var(--rail-w);
  width: var(--rail-w);
  display: flex;
  flex-direction: column;
  padding: var(--sp-5) var(--sp-4) var(--sp-4);
  border-right: 1px solid var(--border);
  background: linear-gradient(180deg, var(--surface-raised), var(--surface));
  transition: flex-basis var(--dur-slow) var(--ease-out), width var(--dur-slow) var(--ease-out);
}

/* ---------- 品牌 ---------- */
.rail__brand {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 0 6px var(--sp-5);
}

.rail__seal {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  border-radius: var(--r-md);
  overflow: hidden;
}

.rail__seal img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.rail__brand-text h1 {
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
  letter-spacing: 2px;
  line-height: var(--lh-tight);
}

.rail__brand-text span {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
  letter-spacing: 0.5px;
}

/* ---------- 导航项 ---------- */
.rail__nav {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.rail__item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 11px 12px;
  border-radius: var(--r-md);
  color: var(--text-secondary);
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  position: relative;
  text-decoration: none;
  transition:
    background var(--dur-base) var(--ease-out),
    color var(--dur-base) var(--ease-out);
}

.rail__item:hover {
  background: var(--surface-sunken);
  color: var(--text-primary);
  text-decoration: none;
}

.rail__item.is-active {
  background: var(--surface-inverse);
  color: var(--text-on-dark);
}

/* 激活态左侧朱砂标记：位置与 rail padding 对齐 */
.rail__item.is-active::before {
  content: '';
  position: absolute;
  left: calc(var(--sp-4) * -1);
  top: 20%;
  bottom: 20%;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--accent);
}

.rail__en {
  margin-left: auto;
  font-family: var(--font-serif);
  font-style: italic;
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

.rail__item.is-active .rail__en {
  color: var(--accent-soft);
}

/* ---------- 页脚 ---------- */
.rail__footer {
  margin-top: auto;
  padding-top: var(--sp-4);
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.rail__conn {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.rail__dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 50%;
  background: var(--text-tertiary);
  box-shadow: 0 0 0 3px rgba(116, 103, 80, 0.16);
  transition: background var(--dur-slow) var(--ease-out);
}

.rail__dot.is-on {
  background: var(--success);
  box-shadow: 0 0 0 3px rgba(79, 138, 91, 0.18);
}

.rail__dot.is-off {
  background: var(--danger);
  box-shadow: 0 0 0 3px rgba(180, 55, 46, 0.18);
}

.rail__session {
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  user-select: all;
  cursor: text;
}

/* ---------- 折叠态 ---------- */
.rail.is-collapsed {
  flex-basis: var(--rail-w-compact);
  width: var(--rail-w-compact);
  padding-inline: 10px;
  align-items: center;
}

.rail.is-collapsed .rail__brand {
  justify-content: center;
  padding-inline: 0;
}

.rail.is-collapsed .rail__brand-text,
.rail.is-collapsed .rail__label,
.rail.is-collapsed .rail__en,
.rail.is-collapsed .rail__conn-text,
.rail.is-collapsed .rail__session {
  display: none;
}

.rail.is-collapsed .rail__item {
  justify-content: center;
  padding: 12px;
}

.rail.is-collapsed .rail__item.is-active::before {
  left: -10px;
}

.rail.is-collapsed .rail__footer {
  width: 100%;
  align-items: center;
}

/* ---------- 响应式：窄屏自动折叠，腾出内容宽度 ---------- */
@media (max-width: 1100px) {
  .rail {
    flex-basis: var(--rail-w-compact);
    width: var(--rail-w-compact);
    padding-inline: 10px;
    align-items: center;
  }

  .rail__brand {
    justify-content: center;
    padding-inline: 0;
  }

  .rail__brand-text,
  .rail__label,
  .rail__en,
  .rail__conn-text,
  .rail__session {
    display: none;
  }

  .rail__item {
    justify-content: center;
    padding: 12px;
  }

  .rail__item.is-active::before {
    left: -10px;
  }

  .rail__footer {
    width: 100%;
    align-items: center;
  }
}
</style>
