<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppDrawer from '@/components/ui/AppDrawer.vue'
import AppEmpty from '@/components/ui/AppEmpty.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { toastOk } from '@/components/ui/useToast'
import { useTurnStore } from '@/stores/turn'
import { useWriteStore } from '@/stores/write'
import { splitReply } from '@/core/domain/citations'
import { toPlainText } from '@/core/domain/richtext'

/**
 * 从对话摘取。
 *
 * 这是本产品最独特的闭环：把一次咨询里的洞察沉淀成可被检索的周记原则。
 * 后端落盘就是 Markdown，所以摘取内容用 `> 引用块` 包裹来源，保留出处。
 */

const props = withDefaults(
  defineProps<{
    open: boolean
    /** 触发摘取的段落：面板打开时自动选中它，省去用户再点一次 */
    initialTarget?: 'problem' | 'analysis' | 'solution'
  }>(),
  { initialTarget: 'problem' },
)
const emit = defineEmits<{ close: [] }>()

const turnStore = useTurnStore()
const write = useWriteStore()

onMounted(() => {
  // 用户可能直接从编辑页进来（没经过 ChatView），此时 turn store 还是空的。
  // 打开面板时从会话历史还原一次，保证任何入口都能摘取。
  turnStore.hydrate()
})

watch(
  () => props.open,
  (open) => {
    if (open) {
      turnStore.hydrate()
      // 从某一段的按钮触发时，默认插入目标就是那一段
      target.value = props.initialTarget
      capturedSelection.value = ''
      expandedId.value = null
    }
  },
)

type Section = 'problem' | 'analysis' | 'solution'

const SECTION_LABEL: Record<Section, string> = {
  problem: '① problem · 问题',
  analysis: '② analysis · 分析',
  solution: '③ solution · 方案',
}

interface Candidate {
  id: string
  kind: 'report' | 'turn'
  title: string
  excerpt: string
  body: string
  turnIndex: number
}

const filter = ref('')
const target = ref<Section>(props.initialTarget)
/** 展开全文的候选 id（支持逐条展开看原文，便于挑选句子） */
const expandedId = ref<string | null>(null)

/**
 * 缓存用户选中的片段。
 *
 * 关键：不能在点击「插入」时直接读 window.getSelection() ——
 * 浏览器在 mousedown/click 时会先清除选区，读到的永远是空字符串。
 * 必须在 mouseup 与 selectionchange 时就把它记下来。
 */
const capturedSelection = ref('')

function captureSelection() {
  const el = document.querySelector('.pick__full-text')
  if (!el) {
    capturedSelection.value = ''
    return
  }
  const sel = window.getSelection()
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
    capturedSelection.value = ''
    return
  }
  // 只接受「选区落在当前展开的全文里」的情况
  const range = sel.getRangeAt(0)
  if (!el.contains(range.commonAncestorContainer)) {
    capturedSelection.value = ''
    return
  }
  capturedSelection.value = sel.toString().trim()
}

function onTextMouseUp() {
  // 等浏览器完成选区更新
  requestAnimationFrame(captureSelection)
}

function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
  capturedSelection.value = ''
}

const candidates = computed<Candidate[]>(() => {
  const out: Candidate[] = []

  for (const turn of turnStore.turns) {
    if (turn.status === 'running') continue

    const segments = splitReply(turn.reply)

    // 建议报告优先：它是整轮咨询的沉淀，最适合摘入 solution
    for (const seg of segments) {
      if (seg.kind !== 'advice') continue
      const body = toPlainText(seg.content)
      out.push({
        id: `${turn.id}-report`,
        kind: 'report',
        title: '建议总结',
        excerpt: body.slice(0, 120),
        body,
        turnIndex: turn.index,
      })
    }

    // 对话轮次（用户提问 + 回答摘要）
    const answer = segments
      .filter((s) => s.kind === 'text')
      .map((s) => toPlainText(s.content))
      .join('\n')

    if (answer) {
      const q = toPlainText(turn.userText)
      out.push({
        id: `${turn.id}-turn`,
        kind: 'turn',
        title: q.length > 26 ? q.slice(0, 26) + '…' : q || `第 ${turn.index + 1} 轮`,
        excerpt: answer.slice(0, 120),
        body: answer,
        turnIndex: turn.index,
      })
    }
  }

  return out
})

const filtered = computed(() => {
  const kw = filter.value.trim().toLowerCase()
  if (!kw) return candidates.value
  return candidates.value.filter(
    (c) => c.title.toLowerCase().includes(kw) || c.excerpt.toLowerCase().includes(kw),
  )
})

function insert(c: Candidate) {
  /*
   * 若用户在展开的全文里选中了一段，只插入选中部分。
   * 用 capturedSelection（mouseup 时缓存）而非实时读选区 ——
   * 点击按钮时浏览器已清除选区，实时读永远是空字符串。
   */
  const sel = capturedSelection.value
  const useSelection = sel.length > 0 && expandedId.value === c.id
  const body = useSelection ? sel : c.body

  const quote = body
    .split('\n')
    .map((line) => (line.trim() ? `> ${line}` : '>'))
    .join('\n')

  const label = c.kind === 'report' ? '的建议总结' : ''
  const source = useSelection
    ? `> 摘自对话第 ${c.turnIndex + 1} 轮${label}`
    : `> 来自对话第 ${c.turnIndex + 1} 轮${label}`
  const block = `\n\n${source}\n\n${quote}\n\n`

  write.setSection(target.value, write[target.value] + block)
  capturedSelection.value = ''
  toastOk(
    useSelection
      ? `已摘取选中片段 ${body.length} 字 → ${SECTION_LABEL[target.value]}`
      : `已插入完整内容 → ${SECTION_LABEL[target.value]}`,
    3500,
  )
}

function isEmpty() {
  return candidates.value.length === 0
}
</script>

<template>
  <AppDrawer :open="open" title="从对话摘取" width="560px" @close="emit('close')">
    <div v-if="isEmpty()" class="pick__empty-wrap">
      <AppEmpty
        icon="chat"
        title="还没有可摘取的对话"
        desc="先到「主对话」完成一轮咨询"
      />
    </div>

    <template v-else>
      <!-- 插入目标 -->
      <div class="pick__target">
        <span class="pick__target-label">插入到</span>
        <div class="pick__targets" role="group" aria-label="插入目标段落">
          <button
            v-for="s in (['problem', 'analysis', 'solution'] as Section[])"
            :key="s"
            type="button"
            class="pick__target-btn"
            :class="{ 'is-active': target === s }"
            :aria-pressed="target === s"
            @click="target = s"
          >
            {{ SECTION_LABEL[s] }}
          </button>
        </div>
      </div>

      <input v-model="filter" class="c-input pick__filter" placeholder="搜索对话内容…" />

      <div class="pick__list">
        <article v-for="c in filtered" :key="c.id" class="pick__item">
          <header class="pick__item-head">
            <span class="pick__kind" :class="`pick__kind--${c.kind}`">
              <AppIcon :name="c.kind === 'report' ? 'sparkle' : 'chat'" :size="10" />
              {{ c.kind === 'report' ? '建议报告' : `第 ${c.turnIndex + 1} 轮` }}
            </span>
            <span class="pick__title">{{ c.title }}</span>
          </header>

          <!-- 收起态：摘要；展开态：全文（可选中片段后只插入选中部分） -->
          <p v-if="expandedId !== c.id" class="pick__excerpt">{{ c.excerpt }}…</p>
          <div v-else class="pick__full">
            <p class="pick__full-hint" :class="{ 'is-active': capturedSelection }">
              <template v-if="capturedSelection">
                已选中 {{ capturedSelection.length }} 字 · 点下方按钮只摘取这一段
              </template>
              <template v-else>
                选中任意片段可只插入那几句
              </template>
            </p>
            <p class="pick__full-text" @mouseup="onTextMouseUp">{{ c.body }}</p>
          </div>

          <div class="pick__item-actions">
            <AppButton size="sm" variant="quiet" @click="toggleExpand(c.id)">
              {{ expandedId === c.id ? '收起' : '展开全文' }}
            </AppButton>
            <AppButton
              size="sm"
              :variant="capturedSelection && expandedId === c.id ? 'primary' : 'ghost'"
              icon="plus"
              @click="insert(c)"
            >
              {{
                capturedSelection && expandedId === c.id
                  ? `插入选中 ${capturedSelection.length} 字`
                  : `插入到 ${SECTION_LABEL[target].slice(0, 4)}`
              }}
            </AppButton>
          </div>
        </article>

        <AppEmpty
          v-if="!filtered.length"
          icon="search"
          title="没有匹配的内容"
          desc="换个关键词试试"
        />
      </div>
    </template>

    <template #foot>
      <div class="pick__foot">
        <AppButton variant="ghost" @click="emit('close')">完成</AppButton>
      </div>
    </template>
  </AppDrawer>
</template>

<style scoped>
.pick__empty-wrap {
  padding: var(--sp-4) 0;
}

/* ---------- 插入目标 ---------- */
.pick__target {
  margin-bottom: var(--sp-3);
}

.pick__target-label {
  display: block;
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
  margin-bottom: 5px;
}

.pick__targets {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.pick__target-btn {
  padding: 4px 10px;
  border-radius: var(--r-pill);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--fs-2xs);
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.pick__target-btn:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.pick__target-btn.is-active {
  background: var(--surface-inverse);
  border-color: var(--surface-inverse);
  color: var(--text-on-dark);
}

.pick__filter {
  margin-bottom: var(--sp-3);
  font-size: var(--fs-xs);
}

/* ---------- 候选列表 ---------- */
.pick__list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.pick__item {
  padding: var(--sp-3);
  border: 1px solid var(--border-soft);
  border-radius: var(--r-md);
  background: var(--surface-raised);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.pick__item-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.pick__kind {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 7px;
  border-radius: var(--r-pill);
  font-family: var(--font-mono);
  font-size: 9.5px;
  white-space: nowrap;
}

.pick__kind--report {
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
}

.pick__kind--turn {
  background: var(--surface-sunken);
  color: var(--text-secondary);
}

.pick__title {
  font-family: var(--font-serif);
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  color: var(--text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pick__excerpt {
  font-size: var(--fs-2xs);
  line-height: var(--lh-body);
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---------- 全文展开 ---------- */
.pick__full {
  max-height: 40vh;
  overflow-y: auto;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-sm);
  background: var(--surface);
  border: 1px solid var(--border-soft);
}

.pick__full-hint {
  margin-bottom: var(--sp-2);
  padding-bottom: var(--sp-1);
  border-bottom: 1px dashed var(--border-soft);
  font-size: 12px;
  color: var(--text-tertiary);
}

/* 已选中时高亮提示，让用户确认「这次会只插入选中的部分」 */
.pick__full-hint.is-active {
  color: var(--accent-deep);
  font-weight: var(--fw-medium);
}

/* 全文按正文排版，方便逐句挑选 */
.pick__full-text {
  font-size: 14.5px;
  line-height: 1.9;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  user-select: text;
}

.pick__item-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
}

.pick__foot {
  display: flex;
  justify-content: flex-end;
}
</style>
