import { API_BASE, API } from '@/core/api/endpoints'
import type { ChatRequest, ChatStreamEvent, TraceItem } from '@/core/api/types'

/**
 * `/chat/stream` 客户端。
 *
 * 后端是**伪流式**（api/chat.py）：先 run_in_executor 把整个 agent_service_entry 跑完，
 * 才依次推 meta → trace_all → 8 字符切片 reply_chunk → finish。
 * 所以「首字延迟 = 完整生成耗时」，等待期的进度感只能靠旁路订阅 /trace/stream
 * （见 stores/turn.ts 与 TurnTrace 组件）。
 *
 * 这里只负责：正确解析帧、把每类事件分发给回调、支持中途取消。
 */

export interface ChatStreamHandlers {
  /** 消息身份与是否结束，在 reply_chunk 之前到达 */
  onMeta?: (meta: { intent_type: string; ended: boolean }) => void
  /** 全流程日志（一次性全量） */
  onTraceAll?: (logs: TraceItem[]) => void
  /** 逐段正文 */
  onChunk?: (text: string) => void
  /** 后端兜底错误 */
  onError?: (message: string) => void
  onFinish?: () => void
}

export interface StreamChatOptions {
  signal?: AbortSignal
}

/**
 * 解析 SSE 帧。
 * 一个帧以空行分隔，内部可能有多个 data: 行，需要拼接后再 JSON.parse。
 *
 * 注意行尾：sse_starlette 实际输出 **CRLF (`\r\n`)**，
 * 所以帧分隔符是 `\r\n\r\n` 而不是 `\n\n`。切帧时必须容忍两种形式，
 * 否则一帧都切不出来（曾经按 `\n\n` 切导致正文完全收不到）。
 */
function parseFrame(raw: string): ChatStreamEvent | null {
  const dataLines: string[] = []
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return null

  const joined = dataLines.join('')
  if (!joined) return null

  try {
    return JSON.parse(joined) as ChatStreamEvent
  } catch {
    return null
  }
}

/** 在缓冲区里找下一个帧分隔符，返回 [帧结束位置, 分隔符长度] */
function findFrameBoundary(buf: string): [number, number] | null {
  const lf = buf.indexOf('\n\n')
  const crlf = buf.indexOf('\r\n\r\n')

  if (crlf >= 0 && (lf < 0 || crlf <= lf)) return [crlf, 4]
  if (lf >= 0) return [lf, 2]
  return null
}

export async function streamChat(
  payload: ChatRequest,
  handlers: ChatStreamHandlers,
  opts: StreamChatOptions = {},
): Promise<void> {
  const res = await fetch(API_BASE + API.chatStream, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: opts.signal,
  })

  if (!res.ok || !res.body) {
    throw new Error(`流式连接失败（HTTP ${res.status}）`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // 按空行切帧（兼容 CRLF 与 LF）；保留最后一个不完整帧
      let boundary: [number, number] | null
      while ((boundary = findFrameBoundary(buffer)) !== null) {
        const [idx, sepLen] = boundary
        const raw = buffer.slice(0, idx)
        buffer = buffer.slice(idx + sepLen)
        dispatch(parseFrame(raw), handlers)
      }
    }

    // 收尾：处理没有以空行结尾的最后一帧
    if (buffer.trim()) dispatch(parseFrame(buffer), handlers)
  } finally {
    reader.releaseLock()
  }
}

function dispatch(evt: ChatStreamEvent | null, handlers: ChatStreamHandlers) {
  if (!evt) return

  switch (evt.type) {
    case 'meta':
      handlers.onMeta?.({ intent_type: evt.intent_type, ended: evt.ended })
      break
    case 'trace_all':
      handlers.onTraceAll?.(evt.logs ?? [])
      break
    case 'reply_chunk':
      handlers.onChunk?.(evt.content ?? '')
      break
    case 'error':
      handlers.onError?.(evt.message || '服务暂时不可用')
      break
    case 'finish':
      handlers.onFinish?.()
      break
  }
}
