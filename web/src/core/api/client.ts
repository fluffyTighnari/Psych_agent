import { API_BASE } from './endpoints'
import { CODE_OK, CODE_SERVER_ERR, type ApiResp } from './types'

/**
 * 业务错误。后端在失败时同样返回 HTTP 200，靠 body 里的 code 区分，
 * 所以不能只看 res.ok。
 */
export class ApiError extends Error {
  constructor(
    readonly code: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** 请求超时（区别于用户主动取消） */
export class ApiTimeoutError extends Error {
  constructor(readonly timeoutMs: number) {
    super(`请求超时（${timeoutMs}ms）`)
    this.name = 'ApiTimeoutError'
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
  /** 外部取消信号（视图切换、用户中止） */
  signal?: AbortSignal
  /** 默认 8s；预处理等长任务传 0 表示不超时 */
  timeoutMs?: number
  /** 网络错误/5xx 的重试次数，默认 1 */
  retries?: number
}

const DEFAULT_TIMEOUT = 8000
const DEFAULT_RETRIES = 1
const BACKOFF_BASE = 300

function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError'
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    function onAbort() {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

async function once<T>(path: string, opts: RequestOptions): Promise<T> {
  const { method = 'GET', body, signal, timeoutMs = DEFAULT_TIMEOUT } = opts

  const controller = new AbortController()
  let timedOut = false

  // 合并外部 signal 与内部超时
  const onExternalAbort = () => controller.abort()
  signal?.addEventListener('abort', onExternalAbort, { once: true })

  let timer: ReturnType<typeof setTimeout> | undefined
  if (timeoutMs > 0) {
    timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)
  }

  try {
    const res = await fetch(API_BASE + path, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })

    /*
     * 响应体必须是统一结构 {code, msg, data}。
     * 若后端某端点漏写 return（FastAPI 会序列化成 null），
     * 这里给出可读错误而不是 `Cannot read properties of null`。
     */
    let json: ApiResp<T>
    try {
      const parsed: unknown = await res.json()
      if (parsed === null || typeof parsed !== 'object') {
        throw new Error('not an object')
      }
      json = parsed as ApiResp<T>
    } catch {
      throw new ApiError(
        CODE_SERVER_ERR,
        `响应格式异常（HTTP ${res.status}）：响应体不是统一结构 {code,msg,data}`,
      )
    }

    // 5xx 由上层决定是否重试
    if (json.code === CODE_SERVER_ERR) {
      throw new ApiError(json.code, json.msg || '服务内部异常', json.extra)
    }
    if (json.code !== CODE_OK) {
      throw new ApiError(json.code, json.msg || `请求失败 code=${json.code}`, json.extra)
    }

    return json.data
  } catch (e) {
    if (timedOut) throw new ApiTimeoutError(timeoutMs)
    if (isAbortError(e)) throw new DOMException('Aborted', 'AbortError')
    throw e
  } finally {
    if (timer) clearTimeout(timer)
    signal?.removeEventListener('abort', onExternalAbort)
  }
}

/**
 * 统一请求入口。
 * - 解包 `code`
 * - 超时（ApiTimeoutError）
 * - 取消（外部 signal → AbortError，不重试）
 * - 网络错误与 5xx 指数退避重试
 */
export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const retries = opts.retries ?? DEFAULT_RETRIES
  let lastError: unknown

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await once<T>(path, opts)
    } catch (e) {
      lastError = e

      // 用户主动取消 / 超时 / 4xx 业务错误：不重试
      if (isAbortError(e)) throw e
      if (e instanceof ApiTimeoutError) throw e
      if (e instanceof ApiError && e.code !== CODE_SERVER_ERR) throw e

      if (attempt < retries) {
        await sleep(BACKOFF_BASE * 2 ** attempt, opts.signal)
        continue
      }
    }
  }

  throw lastError
}

export const api = {
  get: <T>(path: string, opts?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...opts, method: 'GET' }),
  post: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...opts, method: 'POST', body: body ?? {} }),
}

/**
 * 视图级取消域：路由切换时统一中止在途请求，避免旧请求回写已卸载的组件。
 */
export function createRequestScope() {
  const controller = new AbortController()
  return {
    signal: controller.signal,
    abort: () => controller.abort(),
    get aborted() {
      return controller.signal.aborted
    },
  }
}

export type RequestScope = ReturnType<typeof createRequestScope>
