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

  const filter = ref<RecordsFilter>(emptyFilter())
  const vectorQuery = ref('')
  const vectorTopK = ref(3)

  const allDocs = ref<Document[]>([])
  const allMemories = ref<Memory[]>([])

  const results = ref<(Document | Memory)[]>([])
  const loading = ref(false)
  const bootstrapping = ref(true)
  const error = ref<string | null>(null)
  /** 是否已经执行过一次检索（区分「初始列表」与「检索结果」） */
  const searched = ref(false)

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
    error.value = null
    try {
      const [docs, mems] = await Promise.all([dataApi.knowledgeAll({ signal }), dataApi.memoryAll({ signal })])
      allDocs.value = docs
      allMemories.value = mems
      results.value = tab.value === 'knowledge' ? docs : mems
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      bootstrapping.value = false
    }
  }

  /**
   * 切换 tab：总是回落到该 tab 的全量列表。
   * 不保留上一个 tab 的检索结果 —— 否则计数与列表内容属于不同类型，
   * 用户会误以为「记忆有 14 条」而实际那是文档的检索结果。
   */
  function setTab(next: RecordsTab) {
    tab.value = next
    searched.value = false
    error.value = null
    results.value = next === 'knowledge' ? allDocs.value : allMemories.value
  }

  function resetFilter() {
    filter.value = emptyFilter()
    vectorQuery.value = ''
    vectorTopK.value = 3
    searched.value = false
    error.value = null
    results.value = tab.value === 'knowledge' ? allDocs.value : allMemories.value
  }

  async function run(signal?: AbortSignal) {
    error.value = null
    loading.value = true
    const f = filter.value
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
        results.value =
          knowledgeMode.value === 'text'
            ? await searchApi.textFilter({ ...base, target_text: f.targetText }, { signal })
            : await searchApi.metaFilter(base, { signal })
      } else {
        results.value =
          memoryMode.value === 'vector'
            ? await searchApi.memoryVector(
                { query: vectorQuery.value.trim(), top_k: vectorTopK.value },
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
      searched.value = true
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : String(e)
      results.value = []
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
