<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ViewHeader from '@/components/layout/ViewHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppConfirm from '@/components/ui/AppConfirm.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { toastErr, toastInfo, toastOk } from '@/components/ui/useToast'
import ModelDrawer from '@/components/models/ModelDrawer.vue'
import ChatMessage from '@/components/chat/ChatMessage.vue'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import ThreadRail from '@/components/chat/ThreadRail.vue'
import ExecutionChain from '@/components/chat/ExecutionChain.vue'
import GraphCanvas from '@/components/graph/GraphCanvas.vue'
import NodeInspector from '@/components/graph/NodeInspector.vue'
import { toolApi } from '@/core/api'
import { TraceStream } from '@/core/stream/trace-stream'
import { useModelsStore } from '@/stores/models'
import { useSessionStore } from '@/stores/session'
import { useGraphStore } from '@/stores/graph'
import { useChatBridgeStore } from '@/stores/chatBridge'
import { usePeekStore } from '@/stores/peek'
import { useTurnStore } from '@/stores/turn'
import { stripMarks } from '@/core/domain/citations'
import type { ComposerAttachment } from '@/components/chat/ChatComposer.vue'
import { useWriteStore } from '@/stores/write'

const models = useModelsStore()
const session = useSessionStore()
const turnStore = useTurnStore()
const graph = useGraphStore()
const peek = usePeekStore()
const chatBridge = useChatBridgeStore()
const write = useWriteStore()

const scrollRef = ref<HTMLElement | null>(null)
const composerRef = ref<InstanceType<typeof ChatComposer> | null>(null)
const drawerRef = ref<InstanceType<typeof ModelDrawer> | null>(null)

const drawerOpen = ref(false)
/*
 * 图谱面板宽度与折叠状态。
 * 宽度可拖（280–560），记忆在 localStorage —— 不同用户对「看结构」和
 * 「读文档」的空间诉求差异很大，写死一个值必然有人不满。
 */
const GRAPH_MIN = 280
const GRAPH_MAX = 560
const GRAPH_DEFAULT = 380

function readGraphWidth(): number {
  try {
    const raw = localStorage.getItem('psy:graph-width')
    const n = raw ? Number(raw) : NaN
    return Number.isFinite(n) ? Math.max(GRAPH_MIN, Math.min(GRAPH_MAX, n)) : GRAPH_DEFAULT
  } catch {
    return GRAPH_DEFAULT
  }
}

const graphWidth = ref(readGraphWidth())
const graphOpen = ref(true)
const graphNarrow = ref(false)

function setGraphWidth(px: number) {
  graphWidth.value = Math.max(GRAPH_MIN, Math.min(GRAPH_MAX, Math.round(px)))
  try {
    localStorage.setItem('psy:graph-width', String(graphWidth.value))
  } catch {
    // 隐私模式：宽度不持久化不影响使用
  }
}

/* 拖拽调宽 */
let graphResizing = false
let graphStartX = 0
let graphStartW = 0

function onGraphResizeStart(e: PointerEvent) {
  graphResizing = true
  graphStartX = e.clientX
  graphStartW = graphWidth.value
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
}

function onGraphResizeMove(e: PointerEvent) {
  if (!graphResizing) return
  // 图谱在右侧：向左拖 = 变宽
  setGraphWidth(graphStartW + (graphStartX - e.clientX))
}

function onGraphResizeEnd(e: PointerEvent) {
  if (!graphResizing) return
  graphResizing = false
  try {
    ;(e.target as HTMLElement).releasePointerCapture(e.pointerId)
  } catch {
    // 指针已释放
  }
}

function onWindowResize() {
  graphNarrow.value = window.innerWidth < 1100
}
const activeTurnId = ref<string | null>(null)
const showJumpToLatest = ref(false)
const hoveredCitation = ref<string | null>(null)

/**
 * 输入框上方的引用附件。
 * 两种来源：① 从记录页/预览「在对话中追问」带过来的文档；② 消息操作栏点「追问」。
 * 发送后清空。
 */
const attachments = ref<ComposerAttachment[]>([])

function addAttachment(a: ComposerAttachment) {
  if (attachments.value.some((x) => x.id === a.id)) return
  attachments.value = [...attachments.value, a]
}

function removeAttachment(id: string) {
  attachments.value = attachments.value.filter((x) => x.id !== id)
}

/** 点某条回复的「追问」：把该条内容作为 message 附件挂到输入框 */
function onReplyTo(turn: typeof turnStore.turns[number], which: 'guide' | 'advisor') {
  const plain = stripMarks(turn.reply)
  if (!plain) return
  addAttachment({
    id: `msg-${turn.id}`,
    kind: 'message',
    title: which === 'guide' ? `引导者第 ${turn.index + 1} 问` : `建议者第 ${turn.index + 1} 轮`,
    content: plain,
    role: which,
  })
  composerRef.value?.focusInput()
}

type PendingAction = 'clear' | 'reset'
const confirmAction = ref<PendingAction | null>(null)
const confirming = ref(false)

let traceStream: TraceStream | null = null
let observer: IntersectionObserver | null = null

const NEAR_BOTTOM_PX = 80

const turns = computed(() => turnStore.turns)
const isEmpty = computed(() => turns.value.length === 0)

/* ---------- 智能贴底 ---------- */

function nearBottom(): boolean {
  const el = scrollRef.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
}

function scrollToBottom(smooth = false) {
  const el = scrollRef.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  showJumpToLatest.value = false
}

function onScroll() {
  // 用户上翻后停止自动跟随，浮出「回到最新」
  showJumpToLatest.value = !nearBottom()
}

/** 流式追加时的跟随策略：贴底才跟，用户正在上翻就不打扰 */
function followIfNearBottom() {
  if (nearBottom()) nextTick(() => scrollToBottom())
}

/* ---------- 视口高亮（ThreadRail 用） ---------- */

function setupObserver() {
  observer?.disconnect()
  const root = scrollRef.value
  if (!root) return

  observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((e) => e.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)
      const first = visible[0]?.target as HTMLElement | undefined
      if (first?.dataset.turnId) activeTurnId.value = first.dataset.turnId
    },
    { root, threshold: [0.2, 0.6] },
  )

  root.querySelectorAll('[data-turn-id]').forEach((el) => observer?.observe(el))
}

watch(
  () => turns.value.length,
  () => nextTick(setupObserver),
)

/* ---------- 发送 ---------- */

async function onSend(text: string, situation: string | null) {
  if (turnStore.sending) return

  const atts = attachments.value.map((a) => ({
    kind: a.kind,
    doc_id: a.doc_id,
    title: a.title,
    content: a.content,
    role: a.role,
  }))
  attachments.value = []

  const promise = turnStore.send(text, situation, atts)
  nextTick(() => scrollToBottom())

  // 流式期间持续跟随（贴底时）
  const timer = setInterval(followIfNearBottom, 120)

  await promise
  clearInterval(timer)
  followIfNearBottom()

  /*
   * 每轮对话都会新增引用文档 / 推理节点，图谱必须跟着更新 ——
   * 否则用户做完一轮对话，右侧图谱还停在开聊前的状态。
   */
  void graph.load()

  const last = turns.value[turns.value.length - 1]
  if (last?.ended) {
    toastInfo('本轮引导已结束，建议已生成；可点「一键总结」归档', 5000)
  }
}

function onAbort() {
  turnStore.abort()
}

function onModeUpdate(mode: 'direct' | 'guided') {
  turnStore.pendingMode = mode
}

async function onEndGuided() {
  await turnStore.endGuided()
}

/* ---------- 引用联动 ---------- */

function onCite(id: string) {
  /*
   * 点击引用 → 直接打开原文预览。
   * 原先只是在图谱里高亮 240px 的 Inspector，那里没有正文，
   * 用户看得到「引用了什么」却看不到「引用了什么内容」。
   */
  const doc = turnStore.docs.find((d) => d.doc_id === id)
  if (doc) {
    peek.openDocument(doc)
    graph.setExternalFocus(id)
    return
  }

  const mem = turnStore.memories.find((m) => m.id === id)
  if (mem) {
    peek.openMemory(mem)
    graph.setExternalFocus(id)
    return
  }

  // 推理节点没有独立文档，退回图谱 Inspector
  const node = graph.nodes.find((n) => n.id === id)
  if (node) {
    graph.select(node)
  } else {
    toastInfo(`未找到引用内容：${id}`, 3000)
  }
}

function onCiteHover(id: string | null) {
  hoveredCitation.value = id
  // 双向联动：hover 引用 chip → 图谱对应节点脉冲高亮
  graph.setExternalFocus(id)
}

/* ---------- 跳转 ---------- */

function jumpToTurn(turnId: string) {
  const el = scrollRef.value?.querySelector(`[data-turn-id="${turnId}"]`)
  if (!el) return
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  // 目标描边脉冲，让用户确认到了哪一条
  el.classList.add('is-flash')
  setTimeout(() => el.classList.remove('is-flash'), 1200)
}

/* ---------- 摘入周记 ---------- */

function insertToWeekly(text: string) {
  write.problem = (write.problem ? write.problem + '\n\n' : '') + text
  write.mode = 'weekly'
  demoToast()
}

function demoToast() {
  toastOk('已摘入周记 · 可切到「码字编辑」继续完善', 4000)
  // 直接跳转会让用户来不及确认，这里只提示
}

/* ---------- 破坏性操作 ---------- */

const confirmMeta = computed(() =>
  confirmAction.value === 'reset'
    ? {
        title: '重置会话？',
        message:
          '将清空对话记录、记忆引用与引导推理链，并生成新的 session_id。已归档的历史记忆不受影响，但本轮对话无法恢复。',
        confirmLabel: '重置会话',
      }
    : {
        title: '清空本轮对话？',
        message:
          '将清空当前对话与引导推理链，session_id 与已归档记忆保留。清空后无法恢复本轮对话记录。',
        confirmLabel: '清空对话',
      },
)

async function runConfirmed() {
  if (!confirmAction.value) return
  confirming.value = true
  try {
    if (confirmAction.value === 'reset') {
      await turnStore.resetTurns()
      toastOk('会话已完全重置')
    } else {
      await turnStore.clearTurns()
      toastOk('已清空本轮对话')
    }
    confirmAction.value = null
  } catch (e) {
    toastErr('操作失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    confirming.value = false
  }
}

/**
 * 一键总结：真正调用 /tool/summarize 生成记忆并归档。
 * 此前这里只做了 session.load() —— 点了等于什么都没发生。
 */
async function onSummarize() {
  try {
    const res = await toolApi.summarize({ timeoutMs: 180000 })
    toastOk(res.summary_text || '会话总结完成，已归档为记忆', 5000)
    // 总结会新增记忆，刷新会话状态与图谱
    await Promise.allSettled([
      session.load(),
      graph.load(),
      turnStore.loadReferenceData(),
    ])
  } catch (e) {
    toastErr('总结失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

/* ---------- 生命周期 ---------- */

onMounted(async () => {
  // 取走别的页面「在对话中追问」带过来的引用
  for (const a of chatBridge.take()) addAttachment(a)

  onWindowResize()
  window.addEventListener('resize', onWindowResize)
  turnStore.hydrate()
  await Promise.all([turnStore.loadReferenceData(), graph.load()])
  nextTick(() => {
    scrollToBottom()
    setupObserver()
  })

  // trace 流：把真实阶段喂给进行中的 Turn
  traceStream = new TraceStream({
    onFrame: (frame) => {
      const added = turnStore.ingestTrace(frame.logs)
      if (added) followIfNearBottom()
    },
  })
  traceStream.connect()

  composerRef.value?.focusInput()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
  traceStream?.disconnect()
  traceStream = null
  observer?.disconnect()
  observer = null
})
</script>

<template>
  <div class="chat-view">
    <div class="chat-main">
      <ViewHeader sub="与你的心理咨询师进行一场安静的对话">
        <template #actions>
          <div class="chips" aria-label="当前模型配置">
            <span v-for="c in models.chips" :key="c.slot" class="chip">
              <b>{{ c.slot }}</b>
              <code>{{ c.name }}</code>
            </span>
          </div>
          <AppButton size="sm" icon="sparkle" :disabled="isEmpty" @click="onSummarize">
            一键总结
          </AppButton>
          <AppButton size="sm" icon="settings" @click="drawerOpen = true">模型设置</AppButton>
          <AppButton size="sm" :disabled="isEmpty" @click="confirmAction = 'clear'">清空</AppButton>
          <AppButton size="sm" variant="danger" @click="confirmAction = 'reset'">重置</AppButton>
        </template>
      </ViewHeader>

      <!-- 消息区 + 刻度轨 -->
      <div class="chat-body">
        <div class="chat-scroll-wrap">
          <div ref="scrollRef" class="chat-scroll" @scroll="onScroll">
            <div v-if="isEmpty" class="chat-empty">
              <div class="chat-empty__seal" aria-hidden="true">
                <img
                  class="chat-empty__seal-art"
                  src="/brand/empty-state/boat-vortex-256.png"
                  width="88"
                  height="88"
                  alt=""
                />
              </div>
              <p class="chat-empty__title">此刻，你在想些什么？</p>
              <p class="chat-empty__sub">写下你的情绪、困惑或迷茫，我会认真倾听。</p>
            </div>

            <div v-else class="chat-list">
              <div
                v-for="turn in turns"
                :key="turn.id"
                class="chat-turn"
                :data-turn-id="turn.id"
                :class="{ 'is-flash': false }"
              >
                <!-- 用户消息 -->
                <ChatMessage
                  role="user"
                  :text="turn.userText"
                  :show-actions="true"
                />

                <!-- 助手消息：执行链在头像下方，正文在下 -->
                <ChatMessage
                  role="assistant"
                  :speaker="turn.speaker"
                  :text="turn.reply"
                  :streaming="turn.status === 'running'"
                  :citation-ctx="turnStore.citationContext"
                  :show-actions="turn.status !== 'running'"
                  @cite="onCite"
                  @cite-hover="onCiteHover"
                  @reply-to="onReplyTo(turn, turn.speaker)"
                  @insert-to-weekly="insertToWeekly(turn.reply)"
                >
                  <template #chain>
                    <ExecutionChain :turn="turn" />
                  </template>
                </ChatMessage>
              </div>
            </div>
          </div>

          <!-- 回到最新 -->
          <Transition name="fade">
            <button
              v-if="showJumpToLatest"
              type="button"
              class="jump-latest"
              @click="scrollToBottom(true)"
            >
              <AppIcon name="arrow-down" :size="14" />
              回到最新
            </button>
          </Transition>
        </div>

        <ThreadRail :turns="turns" :active-id="activeTurnId" @jump="jumpToTurn" />

        <!-- 折叠后的恢复条：保留 8px 触手，随时可唤回 -->
        <button
          v-if="!graphOpen && !graphNarrow"
          type="button"
          class="graph-restore"
          aria-label="展开关联图谱"
          title="展开关联图谱"
          @click="graphOpen = true"
        >
          <AppIcon name="link" :size="13" />
        </button>

        <!-- 关联图谱面板 -->
        <aside
          v-if="graphOpen"
          class="graph-pane"
          :class="{ 'is-overlay': graphNarrow }"
          :style="graphNarrow ? undefined : { width: graphWidth + 'px', flexBasis: graphWidth + 'px' }"
          aria-label="会话关联图谱"
        >
          <!-- 左缘拖拽把手：左拖变宽 -->
          <div
            v-if="!graphNarrow"
            class="graph-pane__grip"
            role="separator"
            aria-label="拖动调整图谱宽度"
            aria-orientation="vertical"
            @pointerdown="onGraphResizeStart"
            @pointermove="onGraphResizeMove"
            @pointerup="onGraphResizeEnd"
            @pointercancel="onGraphResizeEnd"
          ></div>

          <header class="graph-pane__head">
            <span class="graph-pane__title">关联图谱</span>
            <!--
              这里不再放「总结」按钮：右上角已有同功能入口，
              同一视图两个总结键只会让人犹豫该点哪个。
            -->
            <div class="graph-pane__actions">
              <button
                type="button"
                class="c-icon-btn"
                aria-label="收起图谱"
                @click="graphOpen = false"
              >
                <AppIcon name="close" :size="13" />
              </button>
            </div>
          </header>

          <GraphCanvas />

          <NodeInspector @jump-turn="jumpToTurn" />
        </aside>
      </div>

      <!-- 输入区 -->
      <ChatComposer
        ref="composerRef"
        :sending="turnStore.sending"
        :mode="turnStore.currentMode"
        :mode-locked="turnStore.modeLocked"
        :anchor-problem="turnStore.anchorProblem"
        :guided-pair-count="session.guidedPairCount"
        :attachments="attachments"
        @send="onSend"
        @remove-attachment="removeAttachment"
        @abort="onAbort"
        @end-guided="onEndGuided"
        @update:mode="onModeUpdate"
      />
    </div>

    <ModelDrawer
      ref="drawerRef"
      :open="drawerOpen"
      @close="drawerOpen = false"
    />

    <AppConfirm
      :open="confirmAction !== null"
      :title="confirmMeta.title"
      :message="confirmMeta.message"
      :confirm-label="confirmMeta.confirmLabel"
      :danger="confirmAction === 'reset'"
      :loading="confirming"
      @confirm="runConfirmed"
      @cancel="confirmAction = null"
    />
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: var(--sp-6) var(--view-pad-x) var(--sp-4);
}

.chat-main {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}

.chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.chip {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 3px 10px;
  border-radius: var(--r-pill);
  border: 1px solid var(--border);
  background: var(--surface-raised);
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  color: var(--text-secondary);
}

.chip b {
  color: var(--accent-deep);
  font-weight: var(--fw-medium);
}

.chip code {
  color: var(--text-primary);
}

/* ---------- 消息区 ---------- */
.chat-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.chat-scroll-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
}

.chat-scroll {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--sp-4) var(--sp-4) var(--sp-3) 0;
}

.chat-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}

.chat-turn {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  border-radius: var(--r-md);
  transition: box-shadow var(--dur-slow) var(--ease-out);
}

/* 跳转定位时的脉冲描边 */
.chat-turn.is-flash {
  box-shadow: 0 0 0 2px var(--accent);
}

.chat-turn__assistant {
  display: flex;
  flex-direction: column;
}

/* ---------- 空态 ---------- */
.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  height: 100%;
  min-height: 320px;
  text-align: center;
  color: var(--text-secondary);
}

.chat-empty__seal {
  display: grid;
  place-items: center;
  width: 96px;
  height: 96px;
  margin-bottom: var(--sp-2);
  border-radius: 50%;
  border: 1.5px solid var(--accent-soft);
  background: var(--surface-raised);
}

.chat-empty__seal-art {
  display: block;
  width: 88px;
  height: 88px;
  object-fit: contain;
  user-select: none;
}

.chat-empty__title {
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
  color: var(--text-primary);
}

.chat-empty__sub {
  font-size: var(--fs-sm);
  color: var(--text-tertiary);
}

/* ---------- 回到最新 ---------- */
.jump-latest {
  position: absolute;
  bottom: var(--sp-4);
  left: 50%;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 14px;
  border-radius: var(--r-pill);
  border: 1px solid var(--border);
  background: var(--surface-inverse);
  color: var(--text-on-dark);
  font-size: var(--fs-xs);
  box-shadow: var(--ef-2);
  cursor: pointer;
  z-index: var(--z-sticky);
}

.jump-latest:hover {
  background: var(--accent);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--dur-base) var(--ease-out);
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ---------- 图谱面板 ---------- */
.graph-pane {
  position: relative;
  /*
   * 宽度由内联样式控制（280–560，可拖拽、记忆在 localStorage）。
   * 不再写死 340px —— 用户对「看结构」和「读文档」的空间诉求差异很大，
   * 文档阅读已解耦到页面级 DocumentPeek，图谱只负责看结构。
   */
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex-grow: 0;
  flex-shrink: 0;
  margin-left: var(--sp-3);
  padding-left: var(--sp-3);
  border-left: 1px solid var(--border);
  /* 让 Inspector 能按面板实际宽度决策，而不是按视口 */
  container-type: inline-size;
  container-name: graphpane;
}

/* 左缘拖拽把手 */
.graph-pane__grip {
  position: absolute;
  left: -4px;
  top: 0;
  bottom: 0;
  width: 8px;
  cursor: col-resize;
  z-index: 2;
}

.graph-pane__grip::after {
  content: '';
  position: absolute;
  left: 3px;
  top: 50%;
  transform: translateY(-50%);
  width: 1px;
  height: 44px;
  background: var(--border-strong);
  opacity: 0;
  transition: opacity var(--dur-base) var(--ease-out);
}

.graph-pane__grip:hover::after {
  opacity: 1;
}

/* 折叠后的恢复条 */
.graph-restore {
  display: grid;
  place-items: center;
  width: 20px;
  flex: 0 0 20px;
  margin-left: var(--sp-1);
  border: none;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.graph-restore:hover {
  background: var(--surface-sunken);
  color: var(--text-primary);
}

/* 窄屏：改为覆盖式抽屉，而不是直接隐藏（隐藏等于功能消失） */
.graph-pane.is-overlay {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(360px, 86vw);
  margin-left: 0;
  padding: var(--sp-3);
  background: var(--surface-raised);
  box-shadow: var(--ef-3);
  z-index: var(--z-sticky);
}

.graph-pane__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  flex: 0 0 auto;
  padding-bottom: var(--sp-1);
}

.graph-pane__title {
  font-family: var(--font-serif);
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
}

.graph-pane__actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

/*
 * Inspector 覆盖在图谱上。
 *
 * 面板默认 380px、可拖到 280px。Inspector 若固定 280px，窄面板打开后
 * 画布只剩 100px —— 那不是"侧栏"，是"画布被挤没了"，看起来像样式坏了。
 * 所以按面板宽度分档：够宽才做侧栏，不够宽就直接覆盖整个面板当抽屉。
 */
@container graphpane (min-width: 460px) {
  .graph-pane :deep(.ins) {
    width: min(300px, 72%);
  }
}

@container graphpane (max-width: 459px) {
  .graph-pane :deep(.ins) {
    width: 100%;
    border-left: none;
  }
}

/* 窄屏由 graphNarrow 控制改为覆盖式抽屉，此处不再隐藏整个面板 */

@media (max-width: 900px) {
  .chat-view {
    padding: var(--sp-4) var(--sp-4) var(--sp-3);
  }

  .chat-scroll {
    padding-right: 0;
  }
}
</style>
