import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { dataApi, searchApi } from '@/core/api'
import type { Document, Memory } from '@/core/api/types'

export const VALID_TOPICS = [
  'Self_Understanding',
  'Self_Acceptance',
  'Personal_Growth',
  'Emotion_Regulation',
  'Anxiety',
  'Uncertainty',
  'Perfectionism',
  'Motivation',
  'Action',
  'Learning',
  'Skill_Development',
  'Career',
  'Relationships',
  'Cognitive_Patterns',
  'Values',
  'Stress_Health',
  'Lifestyle',
  'Psychology',
  'Philosophy',
  'Happiness',
] as const

export const EMOTIONS = [
  'Neutral', 'Anxiety', 'Sadness', 'Anger', 'Fear', 'Joy', 'Hope',
  'Disappointment', 'Confusion', 'Calm', 'Stress', 'Loneliness', 'Guilt',
  'Shame', 'Frustration', 'Gratitude', 'Contentment', 'Excitement', 'Worry',
  'Melancholy', 'Relief', 'Regret', 'Overwhelmed',
] as const

export type RecordsTab = 'knowledge' | 'memory'
export type KnowledgeMode = 'meta' | 'text' | 'preprocess'
export type MemoryMode = 'filter' | 'vector'

/**
 * 每条检索链路各自一份状态。
 *
 * 知识文档与历史记忆是两条独立的检索路径（不同的后端接口、不同的可用字段），
 * 但它们原先共用 filter / searched / results 一份状态：
 *   - 在知识文档里筛过一轮，切到记忆页，筛选条件还留着（语义并不通用）；
 *   - 切回来时 searched 已被重置，「已按条件筛选」标识消失，看起来像从没检索过。
 * 现在按 tab 各存一份，互不影响。
 */
interface TabState {
  filter: RecordsFilter
  vectorQuery: string
  searched: boolean
  /** 该 tab 上一次的检索结果；null 表示还没检索过，回落到全量列表 */
  results: (Document | Memory)[] | null
  error: string | null
}

export interface RecordsFilter {
  docType: string
  startDate: string
  endDate: string
  topics: string[]
  keyword: string
  emotion: string
  targetText: string
}

function emptyFilter(): RecordsFilter {
  return { docType: '', startDate: '', endDate: '', topics: [], keyword: '', emotion: '', targetText: '' }
}

/** 把逗号分隔输入拆成数组，空则 null（后端约定） */
function splitMulti(s: string): string[] | null {
  const arr = s
    .split(/[,，、;；\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
  return arr.length ? arr : null
}

export const useRecordsStore = defineStore('records', () => {
  const tab = ref<RecordsTab>('knowledge')
  const knowledgeMode = ref<KnowledgeMode>('meta')
  const memoryMode = ref<MemoryMode>('filter')

  function emptyTabState(): TabState {
    return { filter: emptyFilter(), vectorQuery: '', searched: false, results: null, error: null }
  }

  /** 两个 tab 各自的状态 */
  const states = ref<Record<RecordsTab, TabState>>({
    knowledge: emptyTabState(),
    memory: emptyTabState(),
  })

  /** 当前 tab 的状态（写入用） */
  const cur = computed(() => states.value[tab.value])

  /*
   * 下面这些保持对外形态不变（视图层用 records.filter.xxx 双向绑定），
   * 内部改成读写"当前 tab 的那一份"。
   */
  const filter = computed({
    get: () => cur.value.filter,
    set: (v: RecordsFilter) => {
      cur.value.filter = v
    },
  })

  const vectorQuery = computed({
    get: () => cur.value.vectorQuery,
    set: (v: string) => {
      cur.value.vectorQuery = v
    },
  })

  const vectorTopK = ref(3)

  const loading = ref(false)
  const bootstrapping = ref(true)
  const error = computed({
    get: () => cur.value.error,
    set: (v: string | null) => {
      cur.value.error = v
    },
  })
  /** 当前 tab 是否已执行过一次检索 */
  const searched = computed({
    get: () => cur.value.searched,
    set: (v: boolean) => {
      cur.value.searched = v
    },
  })

  const allDocs = ref<Document[]>([])
  const allMemories = ref<Memory[]>([])

  /** 当前 tab 的结果：检索过就用检索结果，否则用全量列表 */
  const results = computed<(Document | Memory)[]>(() => {
    const s = cur.value
    if (s.searched && s.results) return s.results
    return tab.value === 'knowledge' ? allDocs.value : allMemories.value
  })

  const hasFilter = computed(() => {
    const f = filter.value
    return !!(
      f.docType ||
      f.startDate ||
      f.endDate ||
      f.topics.length ||
      f.keyword ||
      f.emotion ||
      f.targetText ||
      (memoryMode.value === 'vector' && vectorQuery.value.trim())
    )
  })

  const activeFilterChips = computed(() => {
    const f = filter.value
    const chips: { key: string; label: string; clear: () => void }[] = []
    if (f.docType) chips.push({ key: 'docType', label: f.docType, clear: () => (f.docType = '') })
    if (f.startDate) chips.push({ key: 'start', label: '起 ' + f.startDate, clear: () => (f.startDate = '') })
    if (f.endDate) chips.push({ key: 'end', label: '止 ' + f.endDate, clear: () => (f.endDate = '') })
    f.topics.forEach((t) =>
      chips.push({
        key: 'topic-' + t,
        label: t,
        clear: () => {
          f.topics = f.topics.filter((x) => x !== t)
        },
      }),
    )
    if (f.keyword) chips.push({ key: 'kw', label: '词 ' + f.keyword, clear: () => (f.keyword = '') })
    if (f.emotion) chips.push({ key: 'em', label: '情绪 ' + f.emotion, clear: () => (f.emotion = '') })
    if (f.targetText) chips.push({ key: 'target', label: '原文 ' + f.targetText, clear: () => (f.targetText = '') })
    if (memoryMode.value === 'vector' && vectorQuery.value.trim())
      chips.push({ key: 'vec', label: '查询 ' + vectorQuery.value.trim(), clear: () => (vectorQuery.value = '') })
    return chips
  })

  function toggleTopic(topic: string) {
    const list = filter.value.topics
    filter.value.topics = list.includes(topic)
      ? list.filter((t) => t !== topic)
      : [...list, topic]
  }

  async function bootstrap(signal?: AbortSignal) {
    bootstrapping.value = true
    for (const k of ['knowledge', 'memory'] as const) states.value[k].error = null
    try {
      const [docs, mems] = await Promise.all([dataApi.knowledgeAll({ signal }), dataApi.memoryAll({ signal })])
      allDocs.value = docs
      allMemories.value = mems
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      cur.value.error = e instanceof Error ? e.message : String(e)
    } finally {
      bootstrapping.value = false
    }
  }

  /**
   * 切换 tab。
   * 各 tab 的筛选条件与检索结果**各自保留** —— 两条链路独立，
   * 切回来时应当还是离开时的样子（包括「已按条件筛选」标识）。
   */
  function setTab(next: RecordsTab) {
    tab.value = next
    cur.value.error = null
  }

  function resetFilter() {
    const s = cur.value
    s.filter = emptyFilter()
    s.vectorQuery = ''
    s.searched = false
    s.results = null
    s.error = null
  }

  async function run(signal?: AbortSignal) {
    const s = cur.value
    s.error = null
    loading.value = true
    const f = s.filter
    try {
      if (tab.value === 'knowledge') {
        if (knowledgeMode.value === 'preprocess') {
          // 预处理由视图直接调用 toolApi，这里不处理
          return
        }
        const base = {
          doc_type: f.docType || null,
          start_date: f.startDate || null,
          end_date: f.endDate || null,
          topic_keyword: f.topics.length ? f.topics : null,
          keyword: splitMulti(f.keyword),
          emotion: splitMulti(f.emotion),
        }
        s.results =
          knowledgeMode.value === 'text'
            ? await searchApi.textFilter({ ...base, target_text: f.targetText }, { signal })
            : await searchApi.metaFilter(base, { signal })
      } else {
        s.results =
          memoryMode.value === 'vector'
            ? await searchApi.memoryVector(
                { query: s.vectorQuery.trim(), top_k: vectorTopK.value },
                { signal },
              )
            : await searchApi.memoryFilter(
                {
                  topic_keyword: f.topics.length ? f.topics : null,
                  start_date: f.startDate || null,
                  end_date: f.endDate || null,
                  keyword: splitMulti(f.keyword),
                  emotion: splitMulti(f.emotion),
                },
                { signal },
              )
      }
      s.searched = true
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      s.error = e instanceof Error ? e.message : String(e)
      s.results = []
      s.searched = true
    } finally {
      loading.value = false
    }
  }

  return {
    tab,
    knowledgeMode,
    memoryMode,
    filter,
    vectorQuery,
    vectorTopK,
    allDocs,
    allMemories,
    results,
    loading,
    bootstrapping,
    error,
    searched,
    hasFilter,
    activeFilterChips,
    toggleTopic,
    bootstrap,
    setTab,
    resetFilter,
    run,
  }
})
