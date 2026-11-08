import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { retrievalApi } from '@/core/api'
import type {
  Document,
  RetrievalDebugReq,
  RetrievalDebugResp,
  RetrievalMeta,
} from '@/core/api/types'

/**
 * 检索调试状态。
 *
 * 开关默认值优先取 /retrieval/meta（后端契约），
 * 用户手动改过参数后不再被 meta 覆盖（rdParamsTouched 语义）。
 */

export interface StageSwitch {
  name: string
  label: string
  alias: string
  desc: string
  enabled: boolean
}

export interface RetrievalParams {
  raw_top_k: number
  final_top_k: number
  rrf_k: number
  score_threshold: number | null
}

const FALLBACK_STAGES: StageSwitch[] = [
  { name: 'dense', label: 'Dense 向量召回', alias: '', desc: '语义向量相似度召回，擅长捕捉同义与抽象表达', enabled: true },
  { name: 'bm25', label: 'BM25 关键词召回', alias: '', desc: 'jieba 分词 + 主题/关键词倒排，精确匹配词面', enabled: true },
  { name: 'rrf', label: 'RRF 倒数排名融合', alias: '', desc: '按倒数排名融合多路召回，对齐不同链路的排名', enabled: true },
  { name: 'rerank', label: 'Cross-Encoder 重排', alias: '', desc: '交叉编码器精排上游候选，并按阈值过滤低分', enabled: true },
]

const FALLBACK_PARAMS: RetrievalParams = {
  raw_top_k: 15,
  final_top_k: 3,
  rrf_k: 3,
  score_threshold: null,
}

export const useRetrievalStore = defineStore('retrieval', () => {
  const meta = ref<RetrievalMeta | null>(null)
  const switches = ref<StageSwitch[]>(FALLBACK_STAGES.map((s) => ({ ...s })))
  const params = ref<RetrievalParams>({ ...FALLBACK_PARAMS })

  const query = ref('')
  const result = ref<RetrievalDebugResp | null>(null)
  const running = ref(false)
  const error = ref<string | null>(null)
  /** 用户是否手动改过参数（改过就不再被 meta 覆盖） */
  const paramsTouched = ref(false)

  /** 文档浏览 */
  const docs = ref<Document[]>([])
  const docsLoading = ref(false)
  const docsError = ref<string | null>(null)
  const docFilter = ref('')
  const docTypeFilter = ref('')
  const docTotal = ref(0)
  const docTypeCounts = ref({ daily: 0, weekly: 0 })

  const enabledNames = computed(() => switches.value.filter((s) => s.enabled).map((s) => s.name))
  const hasAnySwitch = computed(() => enabledNames.value.length > 0)
  const canRun = computed(() => query.value.trim().length > 0 && hasAnySwitch.value && !running.value)

  const latency = computed(() => result.value?.latency_ms ?? null)
  const finalCount = computed(
    () => result.value?.final?.count ?? result.value?.final?.results?.length ?? 0,
  )
  const pipelineText = computed(() => {
    const p = result.value?.enabled_pipeline
    return p && p.length ? p.join(' → ') : '尚未运行'
  })

  const filteredDocs = computed(() => {
    const kw = docFilter.value.trim().toLowerCase()
    const type = docTypeFilter.value
    return docs.value.filter((d) => {
      if (type && d.doc_type !== type) return false
      if (!kw) return true
      const hay = [
        d.doc_id,
        d.title,
        d.summary,
        d.content,
        d.problem,
        d.analysis,
        d.solution,
        (Array.isArray(d.topic) ? d.topic.join(' ') : ''),
        (Array.isArray(d.keywords) ? d.keywords.join(' ') : ''),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return hay.includes(kw)
    })
  })

  async function loadMeta(signal?: AbortSignal) {
    try {
      const data = await retrievalApi.meta({ signal })
      meta.value = data

      // 阶段定义：以 meta 为准，缺失的用兜底描述
      const fromMeta = Array.isArray(data.stages) ? data.stages : []
      if (fromMeta.length) {
        const byName = new Map(fromMeta.map((s) => [s.name, s]))
        switches.value = FALLBACK_STAGES.map((def) => {
          const s = byName.get(def.name)
          return {
            name: def.name,
            label: def.label,
            alias: s?.label && s.label !== def.label ? s.label : '',
            desc: s?.desc || def.desc,
            enabled: typeof s?.enabled === 'boolean' ? s.enabled : true,
          }
        })
      }

      // 参数默认值：仅在用户未手动修改时应用
      if (!paramsTouched.value) {
        const d = data.defaults ?? {}
        params.value = {
          raw_top_k: d.raw_top_k ?? FALLBACK_PARAMS.raw_top_k,
          final_top_k: d.final_top_k ?? FALLBACK_PARAMS.final_top_k,
          rrf_k: d.rrf_k ?? FALLBACK_PARAMS.rrf_k,
          score_threshold: d.score_threshold ?? null,
        }
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      // meta 不可用不阻断：用兜底定义继续工作
      meta.value = null
    }
  }

  async function loadDocs(signal?: AbortSignal) {
    docsLoading.value = true
    docsError.value = null
    try {
      const data = await retrievalApi.documents({ signal })
      docs.value = Array.isArray(data.documents) ? data.documents : []
      docTotal.value = data.total ?? docs.value.length
      docTypeCounts.value = {
        daily: data.doc_types?.daily ?? docs.value.filter((d) => d.doc_type === 'daily').length,
        weekly: data.doc_types?.weekly ?? docs.value.filter((d) => d.doc_type === 'weekly').length,
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      docsError.value = e instanceof Error ? e.message : String(e)
    } finally {
      docsLoading.value = false
    }
  }

  function setParam<K extends keyof RetrievalParams>(key: K, value: RetrievalParams[K]) {
    params.value[key] = value
    paramsTouched.value = true
  }

  function toggleSwitch(name: string, enabled: boolean) {
    const s = switches.value.find((x) => x.name === name)
    if (s) s.enabled = enabled
  }

  async function run(signal?: AbortSignal) {
    if (!query.value.trim()) {
      error.value = '请先填写 prompt'
      return
    }
    if (!hasAnySwitch.value) {
      error.value = '至少选择一种检索方式'
      return
    }

    const flags = new Map(switches.value.map((s) => [s.name, s.enabled]))
    const payload: RetrievalDebugReq = {
      query: query.value.trim(),
      dense: !!flags.get('dense'),
      bm25: !!flags.get('bm25'),
      rrf: !!flags.get('rrf'),
      rerank: !!flags.get('rerank'),
      raw_top_k: params.value.raw_top_k,
      final_top_k: params.value.final_top_k,
      rrf_k: params.value.rrf_k,
      score_threshold: params.value.score_threshold,
    }

    running.value = true
    error.value = null
    try {
      result.value = await retrievalApi.debug(payload, { signal, timeoutMs: 180000 })
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : String(e)
      result.value = null
    } finally {
      running.value = false
    }
  }

  return {
    meta,
    switches,
    params,
    query,
    result,
    running,
    error,
    paramsTouched,
    docs,
    docsLoading,
    docsError,
    docFilter,
    docTypeFilter,
    docTotal,
    docTypeCounts,
    enabledNames,
    hasAnySwitch,
    canRun,
    latency,
    finalCount,
    pipelineText,
    filteredDocs,
    loadMeta,
    loadDocs,
    setParam,
    toggleSwitch,
    run,
  }
})
