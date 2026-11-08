import { API_BASE } from '@/core/api/endpoints'
import { API } from '@/core/api/endpoints'
import type { TraceFrame, TraceItem } from '@/core/api/types'

/**
 * `/trace/stream` 的 SSE 客户端。
 *
 * 关键决策（见设计文档 §1.7）：**不按 version 跳变重置视图**。
 * `chat/stream` 开头与 `_ensure_session` 内各 clear_trace() 一次，version 会连跳，
 * 若监听 version 就清空，会丢掉 classify_intent。是否重置由调用方（turn store）决定。
 */

export type TraceStatus = 'connecting' | 'open' | 'error' | 'closed'

export interface TraceStreamCallbacks {
  onFrame?: (frame: TraceFrame) => void
  onStatus?: (status: TraceStatus) => void
}

const MAX_RETRIES = 3
const POLL_FALLBACK_MS = 5000

export class TraceStream {
  private es: EventSource | null = null
  private retries = 0
  private stopped = false
  private pollTimer: ReturnType<typeof setInterval> | null = null
  private lastVersion = 0
  private pollCursor = 0

  version = 0

  constructor(private cb: TraceStreamCallbacks = {}) {}

  connect() {
    this.stopped = false
    this.open()
  }

  private open() {
    if (this.stopped) return
    this.cb.onStatus?.('connecting')

    const es = new EventSource(API_BASE + API.traceStream)
    this.es = es

    es.onopen = () => {
      this.retries = 0
      this.stopPolling()
      this.cb.onStatus?.('open')
    }

    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data) as TraceFrame
        this.version = payload.version ?? 0
        this.lastVersion = this.version
        this.cb.onFrame?.({ version: this.version, logs: payload.logs ?? [] })
      } catch {
        // 单帧解析失败不影响后续帧
      }
    }

    es.onerror = () => {
      this.cb.onStatus?.('error')
      if (this.stopped) return

      // EventSource 自身会重连；连续失败则降级为轮询
      if (++this.retries > MAX_RETRIES) {
        es.close()
        this.es = null
        this.startPolling()
      }
    }
  }

  /** EventSource 不可用时的降级：定时拉 /trace/all */
  private startPolling() {
    if (this.pollTimer) return
    this.pollTimer = setInterval(() => void this.pollOnce(), POLL_FALLBACK_MS)
    void this.pollOnce()
  }

  private stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer)
      this.pollTimer = null
    }
  }

  private async pollOnce() {
    try {
      const res = await fetch(API_BASE + API.traceAll)
      const json = await res.json()
      if (json.code !== 200) return

      const { version, logs } = json.data as { version: number; logs: TraceItem[] }
      if (version !== this.lastVersion) {
        this.lastVersion = version
        this.pollCursor = 0
      }
      if (logs.length > this.pollCursor) {
        const fresh = logs.slice(this.pollCursor)
        this.pollCursor = logs.length
        this.version = version
        this.cb.onFrame?.({ version, logs: fresh })
      }
      this.cb.onStatus?.('open')
    } catch {
      this.cb.onStatus?.('error')
    }
  }

  disconnect() {
    this.stopped = true
    this.es?.close()
    this.es = null
    this.stopPolling()
    this.cb.onStatus?.('closed')
  }
}
