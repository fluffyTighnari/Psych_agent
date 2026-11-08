import { api, type RequestOptions } from './client'
import { API } from './endpoints'
import type {
  ChatRequest,
  ChatResult,
  Document,
  GraphData,
  Memory,
  MemoryFilterReq,
  MetaFilterReq,
  ModelConfigMap,
  OllamaRunningModel,
  RetrievalDebugReq,
  RetrievalDebugResp,
  RetrievalDocsResp,
  RetrievalMeta,
  ModelConnection,
  ConnectionsResp,
  FetchModelsReq,
  FetchModelsResp,
  SaveDailyReq,
  SaveResult,
  SaveWeeklyReq,
  SessionState,
  TextFilterReq,
  TraceAllData,
} from './types'

type Opts = Omit<RequestOptions, 'method' | 'body'>

/* ---------- 会话 ---------- */
export const sessionApi = {
  state: (o?: Opts) => api.get<SessionState>(API.sessionState, o),
  clear: (o?: Opts) => api.post<unknown>(API.sessionClear, {}, o),
  reset: (o?: Opts) => api.post<unknown>(API.sessionReset, {}, o),
}

/* ---------- 对话 ---------- */
export const chatApi = {
  send: (body: ChatRequest, o?: Opts) => api.post<ChatResult>(API.chat, body, o),
  /** 流式走 fetch+ReadableStream，见 core/stream/chat-stream.ts */
  streamPath: API.chatStream,
}

/* ---------- 模型 ---------- */
export const modelApi = {
  get: (o?: Opts) => api.get<ModelConfigMap>(API.modelGet, o),
  update: (body: ModelConfigMap, o?: Opts) => api.post<unknown>(API.modelUpdate, body, o),
  ollamaList: (o?: Opts) => api.get<{ models: string[] }>(API.ollamaList, o),
  ollamaPs: (o?: Opts) => api.get<{ models: OllamaRunningModel[] }>(API.ollamaPs, o),
  ollamaStart: (body: { model_name: string; keep_alive: string }, o?: Opts) =>
    api.post<unknown>(API.ollamaStart, body, o),
}

/* ---------- 模型连接 ---------- */
export const connectionsApi = {
  list: (o?: Opts) => api.get<ConnectionsResp>(API.connections, o),
  upsert: (body: ModelConnection, o?: Opts) =>
    api.post<{ connections: ModelConnection[] }>(API.connections, body, o),
  remove: (id: string, o?: Opts) =>
    api.post<unknown>(API.connections, { id }, { ...o }),
  /** 代理拉取可用模型列表（浏览器直连会 CORS，且 key 不该暴露） */
  fetchModels: (body: FetchModelsReq, o?: Opts) =>
    api.post<FetchModelsResp>(API.connectionsModels, body, { timeoutMs: 30000, ...o }),
}

/* ---------- 数据全量 ---------- */
export const dataApi = {
  knowledgeAll: (o?: Opts) => api.get<Document[]>(API.knowledgeAll, o),
  memoryAll: (o?: Opts) => api.get<Memory[]>(API.memoryAll, o),
  graph: (o?: Opts) => api.get<GraphData>(API.graph, o),
  traceAll: (o?: Opts) => api.get<TraceAllData>(API.traceAll, o),
}

/* ---------- 检索（记录页） ---------- */
export const searchApi = {
  /** 后端返回 {result: T[]} */
  metaFilter: (body: MetaFilterReq, o?: Opts) =>
    api.post<{ result: Document[] }>(API.metaFilter, body, o).then((r) => r.result),
  textFilter: (body: TextFilterReq, o?: Opts) =>
    api.post<{ result: Document[] }>(API.textFilter, body, o).then((r) => r.result),
  memoryFilter: (body: MemoryFilterReq, o?: Opts) =>
    api.post<{ result: Memory[] }>(API.memoryFilter, body, o).then((r) => r.result),
  memoryVector: (body: { query: string; top_k: number }, o?: Opts) =>
    api.post<{ result: Memory[] }>(API.memoryVector, body, o).then((r) => r.result),
}

/* ---------- 工具 ---------- */
export const toolApi = {
  /** 预处理耗时长，不设超时；由调用方传 signal 控制取消 */
  preprocess: (o?: Opts) =>
    api.post<unknown>(API.preprocess, {}, { timeoutMs: 0, retries: 0, ...o }),
  summarize: (o?: Opts) =>
    api.post<{ summary_text: string }>(API.summarize, {}, { timeoutMs: 120000, ...o }),
  saveDaily: (body: SaveDailyReq, o?: Opts) => api.post<SaveResult>(API.saveDaily, body, o),
  saveWeekly: (body: SaveWeeklyReq, o?: Opts) => api.post<SaveResult>(API.saveWeekly, body, o),
}

/* ---------- 检索调试 ---------- */
export const retrievalApi = {
  debug: (body: RetrievalDebugReq, o?: Opts) =>
    // 首次加载本地模型可能很慢，放宽到 2 分钟
    api.post<RetrievalDebugResp>(API.retrievalDebug, body, { timeoutMs: 120000, ...o }),
  documents: (o?: Opts) => api.get<RetrievalDocsResp>(API.retrievalDocs, o),
  document: (docId: string, o?: Opts) =>
    api.get<{ document: Document }>(`${API.retrievalDocs}/${encodeURIComponent(docId)}`, o),
  meta: (o?: Opts) => api.get<RetrievalMeta>(API.retrievalMeta, o),
}

export { API }
export type { RequestOptions }
