import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { chatApi, dataApi } from '@/core/api'
import { buildCitationContext, extractCitations, type Citation, type CitationContext } from '@/core/domain/citations'
import {
  appendStage,
  createTurn,
  finalizeTurn,
  isStaleForTurn,
  turnsFromHistory,
  type Turn,
} from '@/core/domain/turns'
import { streamChat } from '@/core/stream/chat-stream'
import type { ChatAttachment, TraceItem } from '@/core/api/types'
import { useSessionStore } from './session'

/**
 * Turn 聚合 store。
 *
 * 职责边界：
 * - 持有 Turn 列表与「当前进行中的 Turn」
 * - 消费 chat-stream 的正文/身份事件
 * - 接收 trace-stream 推送的阶段（由 ChatView 把 TraceStream 的帧转进来）
 *
 * 不做的事：不直接连 SSE（由视图持有连接生命周期），不负责渲染。
 */

export const useTurnStore = defineStore('turn', () => {
  const session = useSessionStore()

  const turns = ref<Turn[]>([])
  /** 当前进行中的 Turn；null 表示空闲 */
  const active = ref<Turn | null>(null)

  const sending = ref(false)
  /** 用户选择的模式；空表示首条未定 */
  const pendingMode = ref<'direct' | 'guided' | null>(null)
  /** guided 模式锚定的核心问题（首条锁定） */
  const anchorProblem = ref('')

  /** 引用上下文所需的原始数据 */
  const docs = shallowRef<Awaited<ReturnType<typeof dataApi.knowledgeAll>>>([])
  const memories = shallowRef<Awaited<ReturnType<typeof dataApi.memoryAll>>>([])
  const graphNodes = shallowRef<{ id: string; name: string; type: string }[]>([])

  let abortController: AbortController | null = null

  const isEmpty = computed(() => turns.value.length === 0 && !active.value)
  const currentMode = computed<'direct' | 'guided' | null>(
    () => (session.mode as 'direct' | 'guided' | '') || pendingMode.value,
  )
  const modeLocked = computed(() => !!session.mode)

  /** 引用上下文：懒构建，供消息渲染时查序号与标题 */
  const citationContext = computed<CitationContext>(() =>
    buildCitationContext(docs.value, memories.value, graphNodes.value as never),
  )

  /** 全部引用（去重后），按首次出现顺序 */
  const allCitations = computed<Citation[]>(() => {
    const seen = new Map<string, Citation>()
    for (const t of turns.value) {
      const map = extractCitations(t.reply, citationContext.value)
      for (const [id, c] of map) {
        if (!seen.has(id)) seen.set(id, { ...c, index: seen.size + 1 })
      }
    }
    return [...seen.values()]
  })

  async function loadReferenceData(signal?: AbortSignal) {
    const [d, m, g] = await Promise.allSettled([
      dataApi.knowledgeAll({ signal }),
      dataApi.memoryAll({ signal }),
      dataApi.graph({ signal }),
    ])
    if (d.status === 'fulfilled') docs.value = d.value
    if (m.status === 'fulfilled') memories.value = m.value
    if (g.status === 'fulfilled') graphNodes.value = g.value.nodes
  }

  /** 从会话历史还原 Turn 列表 */
  function hydrate() {
    if (active.value) return
    turns.value = turnsFromHistory(session.history, session.state)
  }

  /**
   * 接收 trace 帧。
   * 有进行中的 Turn 时归属给它；否则丢弃（那是别处触发的检索/预处理日志）。
   */
  function ingestTrace(items: TraceItem[]) {
    const turn = active.value
    if (!turn || turn.status !== 'running') return 0

    let added = 0
    for (const item of items) {
      if (isStaleForTurn(item, turn)) continue
      if (appendStage(turn, item)) added++
    }
    return added
  }

  /**
   * 发送一条消息。
   * 返回 Turn 供视图定位；错误已写入 turn.error，不抛出。
   */
  async function send(
    text: string,
    situation: string | null,
    attachments: ChatAttachment[] = [],
  ): Promise<Turn> {
    const mode = currentMode.value ?? 'direct'

    // guided 首条锚定核心问题
    if (mode === 'guided' && !anchorProblem.value) anchorProblem.value = text

    const turn = createTurn({
      index: turns.value.length,
      userText: text,
      situation,
      mode,
    })

    turns.value.push(turn)
    /*
     * 关键：push 之后必须取回「数组里的那个元素」。
     * turns 是 ref([])，Vue 会对元素做深层响应式代理；
     * 若继续持有 push 前的原始对象并在回调里改它，Vue 追踪不到变更，
     * 界面就会卡在「正在处理」而正文其实已经在增长。
     */
    const tracked = turns.value[turns.value.length - 1] as Turn
    active.value = tracked
    sending.value = true
    abortController = new AbortController()

    try {
      await streamChat(
        { user_input: text, situation: situation || null, mode, attachments: attachments.length ? attachments : undefined },
        {
          onMeta: ({ intent_type, ended }) => {
            tracked.intentType = intent_type
            tracked.speaker = intent_type === 'guided_reason' ? 'guide' : 'advisor'
            tracked.ended = ended
          },
          onTraceAll: (logs) => {
            // trace_all 是全量快照，与 trace-stream 的增量按签名去重后合并
            for (const item of logs) {
              if (isStaleForTurn(item, tracked)) continue
              appendStage(tracked, item)
            }
          },
          onChunk: (chunk) => {
            tracked.reply += chunk
          },
          onError: (msg) => {
            tracked.error = msg
          },
          onFinish: () => {
            finalizeTurn(tracked, tracked.error ? 'error' : 'done')
          },
        },
        { signal: abortController.signal },
      )

      // 流正常结束但没收到 finish 事件时的兜底
      if (tracked.status === 'running') finalizeTurn(tracked, tracked.error ? 'error' : 'done')

      // 同步回会话状态，供 ThreadRail / 侧栏显示
      session.appendLocal({ role: 'user', content: text })
      session.appendLocal({
        role: 'assistant',
        content: tracked.reply,
        speaker: tracked.speaker,
      })

      /*
       * 后端在首条消息时锁定会话模式（direct/guided），但本地 session.mode 仍是旧值。
       * 不刷新的话，模式状态条与「结束并生成建议」按钮永远不会出现 ——
       * 因为 modeLocked 依赖 session.mode。
       */
      if (!session.mode) void session.load()
    } catch (e) {
      const aborted = e instanceof DOMException && e.name === 'AbortError'
      if (aborted) {
        finalizeTurn(tracked, 'aborted')
        tracked.error = '已中止生成'
      } else {
        tracked.error = e instanceof Error ? e.message : String(e)
        finalizeTurn(tracked, 'error')
      }
    } finally {
      sending.value = false
      active.value = null
      abortController = null
    }

    return tracked
  }

  function abort() {
    abortController?.abort()
  }

  /** 显式结束引导：guided 模式下让模型收束并生成建议 */
  async function endGuided() {
    if (currentMode.value !== 'guided' || !anchorProblem.value) return
    await send('【结束】', null)
  }

  async function clearTurns() {
    turns.value = []
    active.value = null
    anchorProblem.value = ''
    pendingMode.value = null
    await session.clear()
    await loadReferenceData()
  }

  async function resetTurns() {
    turns.value = []
    active.value = null
    anchorProblem.value = ''
    pendingMode.value = null
    await session.reset()
    await loadReferenceData()
  }

  return {
    turns,
    active,
    sending,
    pendingMode,
    anchorProblem,
    docs,
    memories,
    graphNodes,
    isEmpty,
    currentMode,
    modeLocked,
    citationContext,
    allCitations,
    loadReferenceData,
    hydrate,
    ingestTrace,
    send,
    abort,
    endGuided,
    clearTurns,
    resetTurns,
    streamPath: chatApi.streamPath,
  }
})
