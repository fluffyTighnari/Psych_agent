/**
 * 全部后端路径。与 api/ 下的 @router 一一对应。
 * 集中一处，避免散落在各组件里拼字符串。
 */
export const API = {
  // 对话
  chat: '/chat',
  chatStream: '/chat/stream',

  // 会话
  sessionState: '/session/state',
  sessionClear: '/session/clear',
  sessionReset: '/session/reset',

  // 模型
  modelGet: '/tool/model',
  modelUpdate: '/tool/model/update',
  ollamaList: '/ollama/list',
  ollamaStart: '/ollama/start',
  ollamaPs: '/ollama/ps',
  ollamaHost: '/ollama/host',

  // 模型连接（统一 ollama 与外部 API）
  connections: '/connections',
  connectionsModels: '/connections/models',

  // 检索（记录页）
  metaFilter: '/tool/search/meta-filter',
  textFilter: '/tool/search/text-filter',
  memoryFilter: '/tool/search/memory-filter',
  memoryVector: '/tool/search/memory-vector',

  // 工具
  preprocess: '/tool/preprocess',
  summarize: '/tool/summarize',
  saveDaily: '/tool/article/save-daily',
  saveWeekly: '/tool/article/save-weekly',

  // 全量数据
  knowledgeAll: '/knowledge/all',
  memoryAll: '/memory/all',

  // 图谱
  graph: '/graph/session-relation',

  // 流程日志
  traceAll: '/trace/all',
  traceLatest: '/trace/latest',
  traceStream: '/trace/stream',

  // 检索调试
  retrievalDebug: '/retrieval/debug',
  retrievalDocs: '/retrieval/documents',
  retrievalMeta: '/retrieval/meta',
} as const

/** 以 file:// 打开时回退到本地后端；同源部署用相对路径 */
export const API_BASE = location.protocol === 'file:' ? 'http://127.0.0.1:8000' : ''
