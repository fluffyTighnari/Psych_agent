import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { toolApi } from '@/core/api'
import type { SaveResult } from '@/core/api/types'

export type WriteMode = 'daily' | 'weekly'

const DRAFT_KEY = 'psy:draft'

interface Draft {
  mode: WriteMode
  date: string
  content: string
  filename: string
  title: string
  problem: string
  analysis: string
  solution: string
  savedAt: number
}

function todayISO(): string {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

/** 后端按 年.月.日.md 命名；未选日期时交给后端生成 */
function filenameFromDate(date: string): string | null {
  if (!date) return null
  const [y, m, d] = date.split('-')
  if (!y || !m || !d) return null
  return `${y}.${Number(m)}.${Number(d)}.md`
}

export const useWriteStore = defineStore('write', () => {
  const mode = ref<WriteMode>('daily')

  const date = ref(todayISO())
  const content = ref('')

  const filename = ref('')
  const title = ref('')
  const problem = ref('')
  const analysis = ref('')
  const solution = ref('')

  const saving = ref(false)
  const lastSavedAt = ref<number | null>(null)
  const lastSavedName = ref('')
  /** 草稿自动保存时间，用于状态条提示 */
  const draftSavedAt = ref<number | null>(null)
  /** 最近一次预处理成功的时刻，用于判断「已落盘但未入库」 */
  const lastPreprocessedAt = ref<number | null>(null)

  const charCount = computed(() => {
    const text =
      mode.value === 'daily' ? content.value : `${title.value}${problem.value}${analysis.value}${solution.value}`
    return text.replace(/\s/g, '').length
  })

  const readingMinutes = computed(() => Math.max(1, Math.round(charCount.value / 400)))

  const weeklyFilled = computed(
    () => [problem.value, analysis.value, solution.value].filter((s) => s.trim().length > 0).length,
  )

  const dailyEmpty = computed(() => !content.value.trim())
  const weeklyEmpty = computed(
    () => !filename.value.trim() || !title.value.trim() || weeklyFilled.value === 0,
  )
  const canSave = computed(() => (mode.value === 'daily' ? !dailyEmpty.value : !weeklyEmpty.value))

  const isDirty = computed(() => charCount.value > 0)

  /**
   * 当前编辑内容是否已持久化（落盘到 .md 文件）。
   * 草稿在 localStorage，落盘在 data/notes，两者语义不同：
   * 用户需要知道「现在这份内容会不会丢」。
   */
  const isPersisted = computed(() => {
    if (!lastSavedAt.value) return false
    // 保存之后又改动 → 重新变成未持久化
    return savedSnapshot.value === contentSnapshot.value
  })

  /** 保存瞬间的内容指纹，用于判断之后是否有新改动 */
  const savedSnapshot = ref('')
  const contentSnapshot = computed(() => {
    if (mode.value === 'daily') return content.value
    return `${filename.value}|${title.value}|${problem.value}|${analysis.value}|${solution.value}`
  })

  /* ---------- 草稿：每 2s 防抖写 localStorage ---------- */

  let draftTimer: ReturnType<typeof setTimeout> | null = null

  function scheduleDraft() {
    if (draftTimer) clearTimeout(draftTimer)
    draftTimer = setTimeout(() => persistDraft(), 2000)
  }

  function persistDraft() {
    /*
     * 内容为空时必须**删除**草稿，而不是跳过。
     * 原来的 `if (!isDirty) return` 会让「写过又全删」的场景把旧草稿永远留在
     * localStorage 里，下次进来又被恢复 —— 用户明确删空的内容却又回来了。
     */
    if (!isDirty.value) {
      clearDraft()
      return
    }
    const draft: Draft = {
      mode: mode.value,
      date: date.value,
      content: content.value,
      filename: filename.value,
      title: title.value,
      problem: problem.value,
      analysis: analysis.value,
      solution: solution.value,
      savedAt: Date.now(),
    }
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
      draftSavedAt.value = draft.savedAt
    } catch {
      // 配额满或隐私模式，静默降级：不能因为草稿失败阻断写作
    }
  }

  function restoreDraft(): boolean {
    try {
      const raw = localStorage.getItem(DRAFT_KEY)
      if (!raw) return false
      const d = JSON.parse(raw) as Draft
      mode.value = d.mode ?? 'daily'
      date.value = d.date || todayISO()
      content.value = d.content ?? ''
      filename.value = d.filename ?? ''
      title.value = d.title ?? ''
      problem.value = d.problem ?? ''
      analysis.value = d.analysis ?? ''
      solution.value = d.solution ?? ''
      draftSavedAt.value = d.savedAt ?? null

      // 草稿本身就是空的（历史脏数据）：视为无草稿并清掉
      if (!isDirty.value) {
        clearDraft()
        return false
      }
      return true
    } catch {
      return false
    }
  }

  function clearDraft() {
    try {
      localStorage.removeItem(DRAFT_KEY)
    } catch {
      // 忽略
    }
    draftSavedAt.value = null
  }

  watch(
    () => [content.value, filename.value, title.value, problem.value, analysis.value, solution.value],
    () => scheduleDraft(),
  )

  /* ---------- 保存 ---------- */

  async function saveDaily() {
    saving.value = true
    try {
      const res: SaveResult = await toolApi.saveDaily({
        content: content.value.trim(),
        custom_filename: filenameFromDate(date.value),
      })
      lastSavedAt.value = Date.now()
      lastSavedName.value = res.file_name
      savedSnapshot.value = contentSnapshot.value
      /*
       * 保存后**不清空编辑器内容**。
       * 原来保存即清空，用户看到的是一个空白编辑器加一条转瞬即逝的 Toast，
       * 很容易以为「什么都没发生」或「内容丢了」。保留内容 + 明确状态条
       * 才是持久化该有的反馈。
       */
      clearDraft()
      return res
    } finally {
      saving.value = false
    }
  }

  async function saveWeekly() {
    saving.value = true
    try {
      const res = await toolApi.saveWeekly({
        filename: filename.value.trim(),
        title: title.value.trim(),
        problem: problem.value,
        analysis: analysis.value,
        solution: solution.value,
      })
      lastSavedAt.value = Date.now()
      lastSavedName.value = res.file_name
      savedSnapshot.value = contentSnapshot.value
      // 同上：保留内容，只清草稿
      clearDraft()
      return res
    } finally {
      saving.value = false
    }
  }

  function clearAll() {
    if (mode.value === 'daily') content.value = ''
    else {
      filename.value = ''
      title.value = ''
      problem.value = ''
      analysis.value = ''
      solution.value = ''
    }
    clearDraft()
  }

  /** 从对话摘取时按目标段落写入 */
  function setSection(section: 'problem' | 'analysis' | 'solution', value: string) {
    if (section === 'problem') problem.value = value
    else if (section === 'analysis') analysis.value = value
    else solution.value = value
    // 摘取必然发生在周记语境，自动切到 weekly
    mode.value = 'weekly'
  }

  return {
    mode,
    date,
    content,
    filename,
    title,
    problem,
    analysis,
    solution,
    saving,
    lastSavedAt,
    lastSavedName,
    draftSavedAt,
    lastPreprocessedAt,
    charCount,
    readingMinutes,
    weeklyFilled,
    canSave,
    isDirty,
    isPersisted,
    restoreDraft,
    persistDraft,
    clearDraft,
    saveDaily,
    saveWeekly,
    clearAll,
    setSection,
  }
})
