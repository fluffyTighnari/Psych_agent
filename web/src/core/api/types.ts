/* ==========================================================================
   后端 DTO 类型
   --------------------------------------------------------------------------
   严格对应 api/ 下已实现的返回结构。改动这里之前先核对后端源码，
   不要凭猜测加字段 —— 类型失真的代价比没有类型更大。
   ========================================================================== */

/** 统一响应包装：业务失败也返回 HTTP 200，必须解包 code 判断 */
export interface ApiResp<T> {
  code: number
  msg: string
  data: T
  extra: Record<string, unknown>
}

export const CODE_OK = 200
export const CODE_PARAM_ERR = 400
export const CODE_SERVER_ERR = 500

/* ---------- 知识文档 ---------- */

export type DocType = 'daily' | 'weekly'

export interface Emotion {
  primary?: string
  secondary?: string
  intensity?: number
  primary_emotion?: string
  secondary_emotion?: string
}

export interface Document {
  doc_id: string
  content: string
  title: string
  source: string
  doc_type: DocType | string
  relative_path: string
  knowledge_path: string
  summary: string
  topic: string[]
  keywords: string[]
  emotion: Emotion
  problem?: string | null
  analysis?: string | null
  solution?: string | null
  date?: string | null
  word_count?: number
}

/* ---------- 历史记忆 ---------- */

export interface DialogueTurn {
  role: 'user' | 'assistant' | string
  content: string
}

export interface Memory {
  id: string
  start_time: string
  end_time: string
  title: string
  summary: string
  topics: string[]
  keywords: string[]
  emotion: Emotion
  dialogues: DialogueTurn[]
  insights: string[]
  referenced_documents: string[]
  related_memory: string[]
  guided_reasons: DialogueTurn[]
}

/* ---------- 会话 ---------- */

export type ChatMode = '' | 'direct' | 'guided'
export type Speaker = 'advisor' | 'guide'

export interface ChatHistoryItem {
  role: 'user' | 'assistant'
  content: string
  speaker?: Speaker
}

export interface GuidedReason {
  role: 'guide' | 'user'
  content: string
}

export interface SessionState {
  session_id: string
  last_consult_query: string
  last_role: string
  mode: ChatMode
  mode_problem: string
  mode_situation: string
  guided_ended: boolean
  full_chat_history: ChatHistoryItem[]
  similar_memories: Memory[]
  referenced_doc_ids: string[]
  guided_reasons: GuidedReason[]
}

/* ---------- 对话 ---------- */

export interface ChatAttachment {
  kind: 'document' | 'message'
  doc_id?: string
  title?: string
  content?: string
  role?: 'guide' | 'advisor'
}

export interface ChatRequest {
  user_input: string
  situation?: string | null
  mode?: 'direct' | 'guided' | null
  /** 用户主动引用的资料，优先级高于检索证据 */
  attachments?: ChatAttachment[]
}

export interface ChatResult {
  intent_type: string
  reply: string
  raw_tool_output?: string
  ended?: boolean
  error?: string
}

/* ---------- 流式事件 ---------- */

export interface TraceItem {
  stage: string
  label: string
  content: Record<string, unknown>
  /** Unix 秒（float） */
  timestamp: number
  is_error: boolean
  error_msg: string | null
}

export type ChatStreamEvent =
  | { type: 'meta'; intent_type: string; ended: boolean }
  | { type: 'trace_all'; logs: TraceItem[] }
  | { type: 'reply_chunk'; content: string }
  | { type: 'error'; message: string }
  | { type: 'finish' }

export interface TraceFrame {
  version: number
  logs: TraceItem[]
}

export interface TraceAllData {
  version: number
  logs: TraceItem[]
}

/* ---------- 图谱 ---------- */

export type GraphNodeType = 'session' | 'memory' | 'document' | 'reason'

export type RelationType =
  | 'session_bind_memory'
  | 'session_ref_doc'
  | 'memory_ref_doc'
  | 'memory_related_memory'
  | 'reason_next'
  | 'session_bind_reason'

export interface GraphNode {
  id: string
  name: string
  type: GraphNodeType
  summary?: string
  source?: string
}

export interface GraphLink {
  source: string
  target: string
  relation: RelationType
}

export interface GraphData {
  nodes: GraphNode[]
  links: GraphLink[]
}

/* ---------- 模型配置 ---------- */

export type ModelSlot = 'small' | 'large' | 'chat'
export type ModelDriver = 'ollama' | 'api'

export interface ModelConfig {
  driver: ModelDriver
  ollama_name: string
  /** 后端返回时已脱敏（仅保留首尾 4 位） */
  api_key: string
  base_url: string
  api_model_name: string
  temperature: number
}

export type ModelConfigMap = Record<ModelSlot, ModelConfig>

/* ---------- 模型连接（ollama 与外部 API 统一形态） ---------- */

export type ConnectionKind = 'ollama' | 'openai'

export interface ModelConnection {
  id: string
  name: string
  kind: ConnectionKind
  base_url: string
  /** 后端返回时为脱敏值（含 *） */
  api_key: string
}

export interface ConnectionsResp {
  connections: ModelConnection[]
  ollama_default: string
}

export interface FetchModelsReq {
  connection_id?: string
  kind?: ConnectionKind
  base_url?: string
  api_key?: string
}

export interface FetchModelsResp {
  models: string[]
  kind: ConnectionKind
  base_url: string
}

export interface OllamaRunningModel {
  model?: string
  name?: string
  size?: number
  expires_at?: string
}

/* ---------- 检索调试 ---------- */

export interface RetrievalRankItem {
  rank?: number
  score?: number
  doc_id: string
  doc: Document | null
}

export interface RetrievalStage {
  name: string
  label?: string
  latency_ms?: number
  results: RetrievalRankItem[]
}

export interface RetrievalFinal {
  source: string
  count: number
  doc_ids: string[]
  results: RetrievalRankItem[]
}

export interface RetrievalOptimized {
  search_query?: string
  match_topics?: string[]
  keywords?: string[]
  distinctive_terms?: string[]
  hyde_experience?: string
  hyde_principle?: string
}

export interface RetrievalFinalSummary {
  source: string
  count: number
  doc_ids: string[]
  label?: string
}

export interface RetrievalDebugResp {
  latency_ms: number
  enabled_pipeline: string[]
  optimized: RetrievalOptimized
  stages: RetrievalStage[]
  final: RetrievalFinal
  final_summary: RetrievalFinalSummary
  logs: TraceItem[]
}

export interface RetrievalDebugReq {
  query: string
  dense: boolean
  bm25: boolean
  rrf: boolean
  rerank: boolean
  raw_top_k?: number
  final_top_k?: number
  rrf_k?: number
  score_threshold?: number | null
}

export interface RetrievalMeta {
  stages?: { name: string; label?: string; desc?: string; enabled?: boolean }[]
  defaults?: {
    raw_top_k?: number
    final_top_k?: number
    rrf_k?: number
    score_threshold?: number
  }
}

export interface RetrievalDocsResp {
  documents: Document[]
  doc_types: { daily?: number; weekly?: number }
  total: number
}

/* ---------- 检索（记录页） ---------- */

export interface MetaFilterReq {
  doc_type?: string | null
  start_date?: string | null
  end_date?: string | null
  topic_keyword?: string[] | null
  keyword?: string[] | null
  emotion?: string[] | null
}

export interface TextFilterReq extends MetaFilterReq {
  target_text: string
}

export interface MemoryFilterReq {
  topic_keyword?: string[] | null
  start_date?: string | null
  end_date?: string | null
  keyword?: string[] | null
  emotion?: string[] | null
}

/* ---------- 保存 ---------- */

export interface SaveDailyReq {
  content: string
  custom_filename?: string | null
}

export interface SaveWeeklyReq {
  filename: string
  title: string
  problem: string
  analysis: string
  solution: string
}

export interface SaveResult {
  save_path: string
  file_name: string
  type: DocType
  title?: string
}
