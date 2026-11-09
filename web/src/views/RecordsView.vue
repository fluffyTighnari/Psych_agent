<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import ViewHeader from '@/components/layout/ViewHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppEmpty from '@/components/ui/AppEmpty.vue'
import AppField from '@/components/ui/AppField.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppPill from '@/components/ui/AppPill.vue'
import AppSkeleton from '@/components/ui/AppSkeleton.vue'
import ResultCard from '@/components/records/ResultCard.vue'
import { toastErr, toastOk } from '@/components/ui/useToast'
import { toolApi } from '@/core/api'
import { createRequestScope } from '@/core/api/client'
import { useRecordsStore, VALID_TOPICS } from '@/stores/records'
import { useChatBridgeStore } from '@/stores/chatBridge'
import { usePeekStore } from '@/stores/peek'
import { useWriteStore } from '@/stores/write'
import { useRouter } from 'vue-router'

const records = useRecordsStore()
const write = useWriteStore()
const peek = usePeekStore()
const chatBridge = useChatBridgeStore()
const router = useRouter()
let scope = createRequestScope()

/** 筛选区折叠：默认收起，省出约 140px 给结果列表 */
const filtersOpen = ref(false)

onMounted(() => {
  void records.bootstrap(scope.signal)
})

onBeforeUnmount(() => {
  scope.abort()
})

function newScope() {
  scope.abort()
  scope = createRequestScope()
  return scope.signal
}

const isKnowledge = computed(() => records.tab === 'knowledge')
/*
 * 「预处理」只是知识文档下的一个二级模式，不是全局模式。
 *
 * 原先只判 knowledgeMode，于是：在知识文档里选中「预处理」，再切到「历史记忆检索」，
 * knowledgeMode 仍停在 'preprocess' —— 记忆页继续显示预处理说明、隐藏全部筛选区、
 * 按钮还写着「运行预处理」。两条检索链路本应完全独立。
 */
const isPreprocess = computed(() => isKnowledge.value && records.knowledgeMode === 'preprocess')
const searchLabel = computed(() => (isPreprocess.value ? '运行预处理' : '搜索'))

const results = computed(() => records.results)
const resultCount = computed(() => results.value.length)

const kind = computed(() => (isKnowledge.value ? 'document' : 'memory') as 'document' | 'memory')

/** 高亮词：关键词逐个 + 精准文本 */
const highlightTerms = computed(() => {
  const out: string[] = []
  const kw = records.filter.keyword
  if (kw) out.push(...kw.split(/[,，、;；\s]+/).filter(Boolean))
  if (records.knowledgeMode === 'text' && records.filter.targetText) {
    out.push(records.filter.targetText)
  }
  return out
})

/** 打开文档预览（页面级侧滑，宽度不受当前视图限制） */
function onOpenPeek(item: unknown) {
  if (isKnowledge.value) {
    peek.openDocument(item as never, highlightTerms.value)
  } else {
    peek.openMemory(item as never, highlightTerms.value)
  }
}

function onAskInChat(item: unknown) {
  const it = item as {
    doc_id?: string
    id?: string
    title?: string
    summary?: string
    content?: string
    problem?: string
    analysis?: string
    solution?: string
  }
  const title = it.title || it.doc_id || '未命名'

  // 文档优先全文；记忆只有摘要
  const content = isKnowledge.value
    ? [it.problem, it.analysis, it.solution].filter(Boolean).join('\n\n') ||
      it.content ||
      it.summary ||
      ''
    : it.summary || ''

  if (content.trim()) {
    chatBridge.attach({
      id: `doc-${it.doc_id ?? it.id ?? title}`,
      kind: 'document',
      doc_id: it.doc_id,
      title,
      content,
    })
  }

  void router.push({ name: 'chat' })
  toastOk(`已附上《${title}》· 直接提问即可`, 4000)
}

function onInsertToWeekly(item: unknown) {
  const it = item as { title?: string; summary?: string; content?: string }
  const text = [it.title, it.summary || it.content].filter(Boolean).join('：')
  write.problem = write.problem ? write.problem + '\n\n' + text : text
  write.mode = 'weekly'
  toastOk('已摘入周记 · 可切到「码字编辑」继续完善', 4000)
}

async function onSearch() {
  if (isPreprocess.value) {
    await onPreprocess()
    return
  }
  // 精准文本模式必须填 target_text
  if (isKnowledge.value && records.knowledgeMode === 'text' && !records.filter.targetText.trim()) {
    toastErr('精准文本过滤需要填写原文短句')
    return
  }
  if (!isKnowledge.value && records.memoryMode === 'vector' && !records.vectorQuery.trim()) {
    toastErr('向量检索需要填写自然查询')
    return
  }
  await records.run(newScope())
  if (records.error) toastErr('检索失败：' + records.error)
}

async function onPreprocess() {
  const signal = newScope()
  try {
    await toolApi.preprocess({ signal })
    toastOk('预处理完成，知识库已刷新')
    await records.bootstrap(scope.signal)
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    toastErr('预处理失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

function onReset() {
  records.resetFilter()
}

function setKnowledgeMode(mode: typeof records.knowledgeMode) {
  records.knowledgeMode = mode
}
</script>

<template>
  <div class="app-view">
    <ViewHeader />

    <!-- 一级 tab：知识文档 / 历史记忆 -->
    <!--
      用 button + aria-pressed 而非 role="tablist"：
      标签页语义要求子元素为 role="tab" 且配套 tabpanel，实际这里是
      「两个互斥的视图切换按钮」，tablist 会造成 aria-required-children 违规。
    -->
    <div class="tabs" role="group" aria-label="记录类型">
      <AppPill
        :active="isKnowledge"
        size="md"
        @click="records.setTab('knowledge')"
      >
        知识文档检索
      </AppPill>
      <AppPill :active="!isKnowledge" size="md" @click="records.setTab('memory')">
        历史记忆检索
      </AppPill>
    </div>

    <!-- 二级模式 -->
    <div class="submodes">
      <template v-if="isKnowledge">
        <AppPill
          v-for="m in [
            { key: 'meta', label: '粗略元过滤' },
            { key: 'text', label: '精准文本过滤' },
            { key: 'preprocess', label: '预处理' },
          ]"
          :key="m.key"
          size="sm"
          tone="neutral"
          :active="records.knowledgeMode === m.key"
          @click="setKnowledgeMode(m.key as typeof records.knowledgeMode)"
        >
          {{ m.label }}
        </AppPill>
      </template>
      <template v-else>
        <AppPill
          size="sm"
          tone="neutral"
          :active="records.memoryMode === 'filter'"
          @click="records.memoryMode = 'filter'"
        >
          精准过滤
        </AppPill>
        <AppPill
          size="sm"
          tone="neutral"
          :active="records.memoryMode === 'vector'"
          @click="records.memoryMode = 'vector'"
        >
          向量语义检索
        </AppPill>
      </template>
    </div>

    <!-- 预处理说明 -->
    <div v-if="isPreprocess" class="preprocess-note">
      <p>
        扫描 <code>data/notes/</code> 下的所有 Markdown，调用本地大模型提取结构化 JSON，
        构建向量库与 BM25 索引。
      </p>
      <p class="muted">此操作耗时较长，请耐心等待。</p>
    </div>

    <!-- 筛选区折叠条 -->
    <button
      v-if="!isPreprocess"
      type="button"
      class="filters-toggle"
      :aria-expanded="filtersOpen"
      aria-controls="records-filters"
      @click="filtersOpen = !filtersOpen"
    >
      <AppIcon name="filter" :size="13" />
      <span>筛选条件</span>
      <span v-if="records.activeFilterChips.length" class="filters-toggle__count">
        已选 {{ records.activeFilterChips.length }}
      </span>
      <span v-else class="filters-toggle__hint">未设置 · 展示全部</span>
      <AppIcon
        name="chevron-down"
        :size="13"
        class="filters-toggle__caret"
        :class="{ 'is-open': filtersOpen }"
      />
    </button>

    <!-- 筛选表单 -->
    <div v-if="!isPreprocess" v-show="filtersOpen" id="records-filters" class="filter-form">
      <AppField v-if="isKnowledge" label="文档类型">
        <select v-model="records.filter.docType" class="c-select">
          <option value="">全部</option>
          <option value="daily">daily · 日常</option>
          <option value="weekly">weekly · 周记</option>
        </select>
      </AppField>

      <template v-if="!isKnowledge && records.memoryMode === 'vector'">
        <AppField label="自然查询" class="span-2">
          <input
            v-model="records.vectorQuery"
            class="c-input"
            placeholder="之前聊过关于焦虑的话题"
            @keydown.enter.prevent="onSearch"
          />
        </AppField>
        <AppField label="top_k">
          <input v-model.number="records.vectorTopK" class="c-input" type="number" min="1" max="20" />
        </AppField>
      </template>

      <template v-else>
        <AppField label="起始日期">
          <input v-model="records.filter.startDate" class="c-input" type="date" />
        </AppField>
        <AppField label="结束日期">
          <input v-model="records.filter.endDate" class="c-input" type="date" />
        </AppField>
        <AppField label="关键词（逗号分隔）">
          <input v-model="records.filter.keyword" class="c-input" placeholder="内耗, 完美主义" />
        </AppField>
        <AppField label="情绪（逗号分隔）">
          <input
            v-model="records.filter.emotion"
            class="c-input"
            list="emotions-list"
            placeholder="Anxiety, Sadness"
          />
        </AppField>
        <AppField v-if="isKnowledge && records.knowledgeMode === 'text'" label="精准文本（必填）" class="span-2">
          <input v-model="records.filter.targetText" class="c-input" placeholder="需要精确匹配的原文短句" />
        </AppField>
      </template>
    </div>

    <!-- 主题多选 -->
    <div v-if="!isPreprocess" v-show="filtersOpen" class="topics">
      <p class="topics__label">主题（可多选）</p>
      <div class="topics__grid" role="group" aria-label="主题筛选">
        <AppPill
          v-for="t in VALID_TOPICS"
          :key="t"
          size="sm"
          :active="records.filter.topics.includes(t)"
          @click="records.toggleTopic(t)"
        >
          {{ t }}
        </AppPill>
      </div>
    </div>

    <p v-if="isKnowledge && records.knowledgeMode === 'meta'" class="rule-note">
      条件规则：不同字段之间取交集；同字段多值中「主题 / 情绪」取并集，「关键词」需同时包含。
    </p>

    <!-- 已选条件 -->
    <div v-if="records.activeFilterChips.length" class="active-filters">
      <span class="active-filters__label">已选</span>
      <button
        v-for="c in records.activeFilterChips"
        :key="c.key"
        type="button"
        class="active-filters__chip"
        @click="c.clear()"
      >
        {{ c.label }}
        <span aria-hidden="true">×</span>
      </button>
    </div>

    <div class="actions">
      <AppButton variant="primary" :loading="records.loading" @click="onSearch">
        {{ searchLabel }}
      </AppButton>
      <AppButton variant="ghost" :disabled="!records.hasFilter" @click="onReset">清空</AppButton>
    </div>

    <!-- 结果 -->
    <div class="results-head">
      <span class="results-head__title">检索结果</span>
      <span class="results-head__count tabular">{{ resultCount }} 条</span>
      <span v-if="records.searched" class="results-head__flag">已按条件筛选</span>
    </div>

    <div class="results">
      <AppSkeleton v-if="records.bootstrapping" variant="card" :lines="4" />

      <AppEmpty
        v-else-if="records.error"
        icon="alert"
        tone="error"
        title="加载失败"
        :desc="records.error"
      >
        <AppButton size="sm" variant="primary" icon="refresh" @click="records.bootstrap(newScope())">
          重试
        </AppButton>
      </AppEmpty>

      <AppEmpty
        v-else-if="!results.length"
        :icon="records.searched ? 'search' : 'archive'"
        :title="records.searched ? '没有匹配的结果' : '还没有任何内容'"
        :desc="
          records.searched
            ? '试试放宽日期范围，或减少主题与关键词限制'
            : '先在「码字编辑」中记录一篇日记或周复盘，预处理后即可检索'
        "
      >
        <AppButton v-if="records.searched" size="sm" @click="onReset">清除筛选条件</AppButton>
      </AppEmpty>

      <div v-else class="result-list">
        <ResultCard
          v-for="(item, i) in results"
          :key="(item as any).doc_id || (item as any).id || i"
          :item="(item as any)"
          :kind="kind"
          :terms="highlightTerms"
          @read-full="onOpenPeek"
          @ask-in-chat="onAskInChat"
          @insert-to-weekly="onInsertToWeekly"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 记录页是内容型视图：整页滚动，筛选区随之上移让位给结果 */
.app-view {
  overflow-y: auto;
}

.filters-toggle {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  margin-top: var(--sp-3);
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  background: var(--surface-raised);
  color: var(--text-secondary);
  font-size: var(--fs-xs);
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}

.filters-toggle:hover {
  border-color: var(--border-strong);
  background: var(--surface);
}

.filters-toggle__count {
  padding: 1px 8px;
  border-radius: var(--r-pill);
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
}

.filters-toggle__hint {
  color: var(--text-tertiary);
}

.filters-toggle__caret {
  margin-left: auto;
  color: var(--text-tertiary);
  transition: transform var(--dur-base) var(--ease-out);
}

.filters-toggle__caret.is-open {
  transform: rotate(180deg);
}

.tabs {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
  padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--border);
}

.submodes {
  display: flex;
  gap: 6px;
  margin: var(--sp-4) 0 var(--sp-3);
  flex-wrap: wrap;
}

.filter-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sp-3) var(--sp-4);
}

.filter-form :deep(.span-2) {
  grid-column: span 2;
}

.topics {
  margin-top: var(--sp-4);
}

.topics__label {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.topics__grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.rule-note {
  margin-top: var(--sp-3);
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

.preprocess-note {
  padding: var(--sp-4);
  border: 1px dashed var(--border);
  border-radius: var(--r-md);
  background: var(--surface-raised);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.preprocess-note code {
  font-size: var(--fs-xs);
  color: var(--accent-deep);
}

.muted {
  margin-top: var(--sp-1);
  font-size: var(--fs-xs);
  color: var(--text-tertiary);
}

.active-filters {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: var(--sp-4);
}

.active-filters__label {
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

.active-filters__chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: var(--r-pill);
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
  font-size: var(--fs-2xs);
  transition: background var(--dur-fast) var(--ease-out);
}

.active-filters__chip:hover {
  background: var(--accent-soft);
}

.actions {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
}

.results-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin: var(--sp-5) 0 var(--sp-3);
}

.results-head__title {
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
}

.results-head__count {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  padding: 1px 9px;
  border-radius: var(--r-pill);
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
}

.results-head__flag {
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

/*
 * 滚动归属：整页滚动，而非仅结果区。
 * 之前 .results 独占滚动，导致 1000px 视口里只有 339px 可读
 * （筛选表单占了上半屏且不可折叠），是明确的可用性倒退。
 */
.results {
  padding-bottom: var(--sp-6);
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

/* 窄屏降为两列 / 单列 */
@media (max-width: 1100px) {
  .filter-form {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .filter-form {
    grid-template-columns: 1fr;
  }

  .filter-form :deep(.span-2) {
    grid-column: span 1;
  }
}
</style>
