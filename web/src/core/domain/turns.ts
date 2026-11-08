import type { ChatHistoryItem, SessionState, Speaker, TraceItem } from '@/core/api/types'
import { extractDetail, resolveStage, type StageDetail, type StageKey } from './stages'
import { stripMarks } from './citations'

/**
 * Turn —— 从用户发送到 finish 的完整生命周期。
 *
 * 它是 chat / trace / graph 三条数据流的缝合点：
 * chat-stream 提供正文与身份，trace-stream 提供阶段轨迹，
 * ThreadRail 与图谱从 Turn 反查引用关系与消息定位。
 */

export type TurnStatus = 'running' | 'done' | 'error' | 'aborted'

export interface TurnStage {
  /** 原始 trace 项，保留供展开查看 */
  raw: TraceItem
  key: StageKey
  title: string
  detail: StageDetail | null
  /** 秒（来自 trace timestamp） */
  startedAt: number
  /** 毫秒；null 表示还没有下一个阶段可比 */
  durationMs: number | null
  isError: boolean
}

export interface Turn {
  id: string
  /** 会话内序号，从 0 开始 */
  index: number

  userText: string
  situation: string | null
  mode: 'direct' | 'guided'

  speaker: Speaker
  /** 原始回复文本（含 [[cite:]] 标记） */
  reply: string

  stages: TurnStage[]
  /** 毫秒 */
  startedAt: number
  finishedAt: number | null

  status: TurnStatus
  error: string | null
  /** 引导是否结束 */
  ended: boolean
  intentType: string
}

let seq = 0
export function nextTurnId(): string {
  seq += 1
  return `turn-${Date.now().toString(36)}-${seq}`
}

/** 阶段去重签名：与后端 trace 的唯一性判断一致 */
export function traceSignature(t: TraceItem): string {
  return `${t.timestamp}_${t.stage}_${t.label}_${JSON.stringify(t.content ?? {})}`
}

export function createTurn(params: {
  index: number
  userText: string
  situation: string | null
  mode: 'direct' | 'guided'
  startedAt?: number
}): Turn {
  return {
    id: nextTurnId(),
    index: params.index,
    userText: params.userText,
    situation: params.situation,
    mode: params.mode,
    speaker: params.mode === 'guided' ? 'guide' : 'advisor',
    reply: '',
    stages: [],
    startedAt: params.startedAt ?? Date.now(),
    finishedAt: null,
    status: 'running',
    error: null,
    ended: false,
    intentType: '',
  }
}

/**
 * 把一条 trace 追加为阶段，并把上一阶段的时长补齐。
 * 时长用相邻 timestamp 差值 —— 后端真实时刻，不伪造。
 */
export function appendStage(turn: Turn, item: TraceItem): boolean {
  const sig = traceSignature(item)
  if (turn.stages.some((s) => traceSignature(s.raw) === sig)) return false

  const def = resolveStage(item.stage)
  const stage: TurnStage = {
    raw: item,
    key: def.key,
    title: def.title,
    detail: extractDetail(item),
    startedAt: item.timestamp,
    durationMs: null,
    isError: item.is_error,
  }

  const prev = turn.stages[turn.stages.length - 1]
  if (prev && prev.durationMs === null) {
    prev.durationMs = Math.max(0, (item.timestamp - prev.startedAt) * 1000)
  }

  turn.stages.push(stage)
  return true
}

/** 定稿：补齐最后一段时长并把计时器归零 */
export function finalizeTurn(turn: Turn, status: TurnStatus, finishedAt = Date.now()) {
  turn.status = status
  turn.finishedAt = finishedAt
  const last = turn.stages[turn.stages.length - 1]
  if (last && last.durationMs === null) {
    last.durationMs = Math.max(0, finishedAt - last.startedAt * 1000)
  }
}

/**
 * 整轮耗时（毫秒）。
 * 历史回合并未记录真实时刻（startedAt = 0 是哨兵），此时返回 null，
 * 由 UI 决定不显示耗时 —— 否则会算出「29901124m」这种荒谬数字。
 */
export function turnDuration(turn: Turn): number | null {
  if (turn.startedAt <= 0) return null
  if (!turn.finishedAt) return Date.now() - turn.startedAt
  return turn.finishedAt - turn.startedAt
}

/* ---------- 阶段归属算法 ---------- */

/**
 * 把 trace 项归属到当前进行中的 Turn。
 *
 * **不使用 version 跳变重置视图**（设计文档 §1.7）：
 * `chat/stream` 开头与 `_ensure_session` 内各 clear_trace() 一次，version 会连跳两次。
 * 若监听 version 就清空，第一个跳变会清掉 classify_intent（它发生在
 * _ensure_session 之前）。所以这里只按「是否早于本轮开始」过滤残留。
 */
export const STALE_WINDOW_SEC = 0.5

export function isStaleForTurn(item: TraceItem, turn: Turn): boolean {
  return item.timestamp < turn.startedAt / 1000 - STALE_WINDOW_SEC
}

/** 从历史消息还原 Turn 列表（刷新/恢复会话时用） */
export function turnsFromHistory(
  history: ChatHistoryItem[],
  sessionState: SessionState | null,
): Turn[] {
  const turns: Turn[] = []
  const mode = sessionState?.mode === 'guided' ? 'guided' : 'direct'
  let index = 0

  for (let i = 0; i < history.length; i++) {
    const item = history[i]
    if (!item || item.role !== 'user') continue

    const reply = history[i + 1]
    if (!reply || reply.role !== 'assistant') continue

    const speaker: Speaker = reply.speaker === 'guide' ? 'guide' : 'advisor'
    const turn = createTurn({
      index: index++,
      userText: item.content,
      situation: null,
      mode,
    })
    turn.speaker = speaker
    turn.reply = reply.content
    /*
     * 历史回合没有 trace 可回溯：直接把状态定为 done，并把 startedAt 设为 0 作为
     * 「无真实时刻」的哨兵 —— turnDuration() 见此值返回 null，UI 不显示耗时。
     * 不要试图用 Date.now() 伪造时刻，否则会算出几十亿毫秒。
     */
    turn.startedAt = 0
    turn.status = 'done'
    turn.finishedAt = 0
    turns.push(turn)
    i += 1
  }

  return turns
}

/** Turn 的一句话摘要（ThreadRail 用） */
export function turnSummary(turn: Turn, maxLen = 40): string {
  const text = stripMarks(turn.userText).replace(/\s+/g, ' ')
  return text.length > maxLen ? text.slice(0, maxLen) + '…' : text
}

/** 该 Turn 引用了哪些节点（图谱联动用） */
export function turnCitationIds(turn: Turn): string[] {
  const ids = new Set<string>()
  const re = /\[\[(?:cite|guide):([^\]\n]+)\]\]/g
  let m: RegExpExecArray | null
  while ((m = re.exec(turn.reply)) !== null) {
    if (m[1]) ids.add(m[1])
  }
  // 阶段详情里的文档 ID 也算引用来源
  for (const s of turn.stages) {
    for (const id of s.detail?.docIds ?? []) ids.add(id)
  }
  return [...ids]
}
