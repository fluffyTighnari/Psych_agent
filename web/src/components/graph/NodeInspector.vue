<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useGraphStore } from '@/stores/graph'
import { usePeekStore } from '@/stores/peek'
import { useTurnStore } from '@/stores/turn'
import { stripMarks } from '@/core/domain/citations'

/**
 * 节点详情侧滑面板。
 *
 * 用侧滑而非居中模态：居中会遮住用户正要看的图。
 * 这里还双向联动 —— 列出「哪些对话轮次引用了这个节点」，点击可跳回对话。
 */

const graph = useGraphStore()
const peek = usePeekStore()

const rootRef = ref<HTMLElement | null>(null)

/**
 * 点击面板外部即收起。
 *
 * 用 pointerdown 而非 click：Dragging 图谱时不会误触。
 * 判断依据是「点在面板外」且「不在图谱节点上」——
 * 点节点应当切换到那个节点，而不是先关掉面板再重开。
 */
function onDocPointerDown(e: PointerEvent) {
  if (!node.value) return
  const target = e.target as Node | null
  if (!target) return

  // 面板内部：不关
  if (rootRef.value?.contains(target)) return

  /*
   * 点在图谱画布上：不关。
   *   - 点到节点 → 图谱的 click 会切换选中，若先关再开会闪一下
   *   - 点到空白 → 保持面板，避免误触（用户可能只是拖拽平移）
   */
  const el = target as HTMLElement
  if (el.closest?.('.gc__canvas') || el.closest?.('.graph-svg')) return

  graph.select(null)
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocPointerDown, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocPointerDown, true)
})
const turnStore = useTurnStore()

/** 文档/记忆节点可打开原文预览；推理节点没有独立正文 */
const canRead = computed(() => node.value?.type === 'document' || node.value?.type === 'memory')

const emit = defineEmits<{ jumpTurn: [turnId: string] }>()

const node = computed(() => graph.selected)

const neighbors = computed(() => (node.value ? graph.neighborsOf(node.value.id) : []))

/** 引用了该节点的对话轮次 */
const referencingTurns = computed(() => {
  const id = node.value?.id
  if (!id) return []
  return turnStore.turns
    .filter((t) => {
      if (t.reply.includes(`[[cite:${id}]]`) || t.reply.includes(`[[guide:${id}]]`)) return true
      return t.stages.some((s) => s.detail?.docIds?.includes(id))
    })
    .map((t) => ({
      id: t.id,
      index: t.index,
      text: stripMarks(t.userText).slice(0, 46),
    }))
})

const TYPE_LABEL: Record<string, string> = {
  session: '会话',
  memory: '记忆',
  document: '文档',
  reason: '推理',
}

const TYPE_ICON = {
  session: 'chat',
  memory: 'memory',
  document: 'doc',
  reason: 'route',
} as const

function openPeek() {
  const n = node.value
  if (!n) return
  if (n.type === 'document') {
    const doc = turnStore.docs.find((d) => d.doc_id === n.id)
    if (doc) {
      peek.openDocument(doc)
      return
    }
  }
  if (n.type === 'memory') {
    const mem = turnStore.memories.find((m) => m.id === n.id)
    if (mem) {
      peek.openMemory(mem)
      return
    }
  }
}

const RELATION_LABEL: Record<string, string> = {
  session_bind_memory: '会话 → 记忆',
  session_ref_doc: '会话 → 文档',
  memory_ref_doc: '记忆 → 文档',
  memory_related_memory: '记忆 → 记忆',
  reason_next: '推理递进',
  session_bind_reason: '会话 → 推理',
}
</script>

<template>
  <Transition name="inspector">
    <aside v-if="node" ref="rootRef" class="ins" aria-label="节点详情">
      <header class="ins__head">
        <div class="ins__type">
          <AppIcon :name="TYPE_ICON[node.type] ?? 'info'" :size="12" />
          {{ TYPE_LABEL[node.type] ?? node.type }}
        </div>
        <button
          type="button"
          class="c-icon-btn"
          aria-label="关闭节点详情"
          @click="graph.select(null)"
        >
          <AppIcon name="close" :size="14" />
        </button>
      </header>

      <h3 class="ins__title">{{ node.name }}</h3>
      <p v-if="node.id" class="ins__id">{{ node.id }}</p>

      <section v-if="node.summary" class="ins__section">
        <h4>摘要</h4>
        <p class="ins__summary">{{ node.summary }}</p>
      </section>

      <section v-if="node.source" class="ins__section">
        <h4>来源</h4>
        <p class="ins__mono">{{ node.source }}</p>
      </section>

      <section v-if="referencingTurns.length" class="ins__section">
        <h4>引用此节点的对话 <span class="ins__count">{{ referencingTurns.length }}</span></h4>
        <button
          v-for="t in referencingTurns"
          :key="t.id"
          type="button"
          class="ins__turn"
          @click="emit('jumpTurn', t.id)"
        >
          <AppIcon name="chat" :size="11" />
          <span class="ins__turn-text">{{ t.text }}</span>
        </button>
      </section>

      <section v-if="neighbors.length" class="ins__section">
        <h4>关联节点 <span class="ins__count">{{ neighbors.length }}</span></h4>
        <ul class="ins__neighbors">
          <li v-for="n in neighbors" :key="n.id + n.relation">
            <button type="button" class="ins__neighbor" @click="graph.select({ id: n.id, name: n.name, type: n.type })">
              <AppIcon :name="TYPE_ICON[n.type] ?? 'info'" :size="10" />
              <span class="ins__neighbor-name">{{ n.name }}</span>
              <span class="ins__relation">{{ RELATION_LABEL[n.relation] ?? n.relation }}</span>
            </button>
          </li>
        </ul>
      </section>

      <footer class="ins__foot">
        <AppButton
          v-if="canRead"
          size="sm"
          variant="primary"
          icon="maximize"
          @click="openPeek"
        >
          阅读全文
        </AppButton>
        <AppButton size="sm" variant="ghost" @click="graph.select(null)">关闭</AppButton>
      </footer>
    </aside>
  </Transition>
</template>

<style scoped>
.ins {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 280px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-3);
  border-left: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface-raised) 97%, transparent);
  backdrop-filter: blur(6px);
  overflow-y: auto;
  z-index: var(--z-sticky);
}

.ins__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
}

.ins__type {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--r-pill);
  background: var(--surface-sunken);
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  color: var(--text-secondary);
}

.ins__title {
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
  line-height: var(--lh-tight);
}

.ins__id {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-tertiary);
  word-break: break-all;
}

.ins__section {
  margin-top: var(--sp-2);
  flex: 0 0 auto;
}

.ins__section h4 {
  display: flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-sans);
  font-size: var(--fs-2xs);
  font-weight: var(--fw-medium);
  color: var(--text-tertiary);
  letter-spacing: 0.3px;
  margin-bottom: 3px;
}

.ins__count {
  padding: 0 5px;
  border-radius: var(--r-pill);
  background: var(--surface-sunken);
  font-family: var(--font-mono);
}

.ins__summary {
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--text-secondary);
  white-space: pre-wrap;
}

.ins__mono {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-tertiary);
  word-break: break-all;
}

/* 引用该节点的对话轮次 */
.ins__turn {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  width: 100%;
  padding: 4px 6px;
  border: none;
  border-radius: var(--r-sm);
  background: transparent;
  text-align: left;
  font-size: var(--fs-2xs);
  color: var(--text-secondary);
  cursor: pointer;
}

.ins__turn:hover {
  background: var(--surface-sunken);
  color: var(--text-primary);
}

.ins__turn-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 邻接节点 */
.ins__neighbors {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.ins__neighbor {
  display: flex;
  align-items: center;
  gap: 5px;
  width: 100%;
  padding: 3px 6px;
  border: none;
  border-radius: var(--r-sm);
  background: transparent;
  text-align: left;
  font-size: var(--fs-2xs);
  color: var(--text-secondary);
  cursor: pointer;
}

.ins__neighbor:hover {
  background: var(--surface-sunken);
  color: var(--text-primary);
}

.ins__neighbor-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ins__relation {
  margin-left: auto;
  flex: 0 0 auto;
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-disabled);
}

.ins__foot {
  margin-top: auto;
  padding-top: var(--sp-2);
  flex: 0 0 auto;
}

/* ---------- 过渡 ---------- */
.inspector-enter-active,
.inspector-leave-active {
  transition:
    opacity var(--dur-base) var(--ease-out),
    transform var(--dur-base) var(--ease-out);
}

.inspector-enter-from,
.inspector-leave-to {
  opacity: 0;
  transform: translateX(12px);
}
</style>
