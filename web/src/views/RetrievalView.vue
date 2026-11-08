<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import ViewHeader from '@/components/layout/ViewHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppDisclosure from '@/components/ui/AppDisclosure.vue'
import AppEmpty from '@/components/ui/AppEmpty.vue'
import AppField from '@/components/ui/AppField.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppSkeleton from '@/components/ui/AppSkeleton.vue'
import RankShiftChart from '@/components/retrieval/RankShiftChart.vue'
import { toastErr } from '@/components/ui/useToast'
import { createRequestScope } from '@/core/api/client'
import { usePeekStore } from '@/stores/peek'
import { useRetrievalStore } from '@/stores/retrieval'
import type { RetrievalRankItem, TraceItem } from '@/core/api/types'

const rd = useRetrievalStore()
const peek = usePeekStore()
let scope = createRequestScope()

onMounted(() => {
  void rd.loadMeta(scope.signal)
  void rd.loadDocs(scope.signal)
})

onBeforeUnmount(() => scope.abort())

function newScope() {
  scope.abort()
  scope = createRequestScope()
  return scope.signal
}

async function onRun() {
  if (!rd.canRun) {
    if (!rd.query.trim()) toastErr('请先填写 prompt')
    else if (!rd.hasAnySwitch) toastErr('至少选择一种检索方式')
    return
  }
  await rd.run(newScope())
  if (rd.error) toastErr('检索失败：' + rd.error)
}

function onPromptKeydown(e: KeyboardEvent) {
  // Ctrl/Cmd + Enter 运行
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    void onRun()
  }
}

/* ---------- 结果展示 ---------- */

const stages = computed(() => rd.result?.stages ?? [])
const finalResults = computed<RetrievalRankItem[]>(() => rd.result?.final?.results ?? [])
const logs = computed<TraceItem[]>(() => rd.result?.logs ?? [])

const optimized = computed(() => rd.result?.optimized ?? {})
const pipeline = computed(() => rd.result?.enabled_pipeline ?? [])

const finalIdSet = computed(() => {
  const ids = new Set<string>()
  for (const id of rd.result?.final?.doc_ids ?? []) ids.add(String(id))
  for (const r of finalResults.value) if (r.doc_id) ids.add(String(r.doc_id))
  return ids
})

/**
 * 打开原文预览。
 * 检索调试里的文档只带摘要，用户要看全文时不该滚到页面底部去「全部文档」找。
 */
function openDoc(docId: string | null | undefined) {
  if (!docId) return
  const found = rd.docs.find((d) => d.doc_id === docId)
  if (found) {
    peek.openDocument(found)
    return
  }
  // 列表未覆盖时用当前结果里的精简对象兜底（仍可显示标题与摘要）
  toastErr('文档详情未加载，请先刷新文档列表')
}

function scoreText(v: unknown): string {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(4) : '—'
}

function fmtDuration(ms: unknown): string {
  const n = Number(ms)
  if (!Number.isFinite(n)) return '—'
  return n < 1000 ? `${n.toFixed(0)}ms` : `${(n / 1000).toFixed(2)}s`
}

function fmtLogTime(ts: unknown): string {
  const n = Number(ts)
  if (!Number.isFinite(n)) return '—'
  return new Date(n * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}

function logRows(item: TraceItem): [string, unknown][] {
  return Object.entries(item.content ?? {})
}

function isComplex(v: unknown): boolean {
  return v !== null && typeof v === 'object'
}

function formatValue(v: unknown): string {
  return isComplex(v) ? JSON.stringify(v, null, 2) : String(v)
}

const finalHint = computed(() => {
  if (!rd.result) return '尚未运行'
  const src = rd.result.final?.source || '—'
  return `来源 ${src} · ${rd.finalCount} 条`
})

const stageHint = computed(() => {
  if (!rd.result) return '尚未运行'
  return `${stages.value.length} 阶段 · 链路 ${pipeline.value.join(' → ') || '—'}`
})
</script>

<template>
  <div class="app-view">
    <ViewHeader>
      <template #actions>
        <div class="stats">
          <span class="stat">
            <b class="tabular">{{ rd.latency === null ? '—' : fmtDuration(rd.latency) }}</b>
            <i>耗时</i>
          </span>
          <span class="stat">
            <b class="tabular">{{ rd.finalCount }}</b>
            <i>最终条数</i>
          </span>
        </div>
        <AppButton variant="primary" size="sm" :loading="rd.running" :disabled="!rd.canRun" @click="onRun">
          运行检索
        </AppButton>
      </template>
    </ViewHeader>

    <div class="rd-scroll">
      <!-- ================= 检索链路控制 ================= -->
      <section class="rd-panel">
        <header class="rd-panel__head">
          <div class="rd-panel__title-row">
            <span class="rd-panel__title">检索链路</span>
            <span class="rd-panel__hint">{{ rd.pipelineText }}</span>
          </div>
        </header>

        <!-- 开关卡片 -->
        <div class="switches">
          <button
            v-for="s in rd.switches"
            :key="s.name"
            type="button"
            class="switch"
            :class="{ 'is-on': s.enabled }"
            :aria-pressed="s.enabled"
            :title="s.desc"
            @click="rd.toggleSwitch(s.name, !s.enabled)"
          >
            <span class="switch__body">
              <span class="switch__name">
                {{ s.label }}
                <em v-if="s.alias" class="switch__alias">{{ s.alias }}</em>
              </span>
              <span class="switch__desc">{{ s.desc }}</span>
            </span>
            <span class="switch__mark" aria-hidden="true">
              <AppIcon v-if="s.enabled" name="check" :size="10" />
            </span>
          </button>
        </div>

        <!-- 参数 -->
        <div class="params">
          <AppField label="raw_top_k" hint="每路召回候选数">
            <input
              :value="rd.params.raw_top_k"
              class="c-input mono"
              type="number"
              min="1"
              max="50"
              @input="rd.setParam('raw_top_k', Number(($event.target as HTMLInputElement).value))"
            />
          </AppField>
          <AppField label="final_top_k" hint="最终返回数">
            <input
              :value="rd.params.final_top_k"
              class="c-input mono"
              type="number"
              min="1"
              max="50"
              @input="rd.setParam('final_top_k', Number(($event.target as HTMLInputElement).value))"
            />
          </AppField>
          <AppField label="rrf_k" hint="融合常数">
            <input
              :value="rd.params.rrf_k"
              class="c-input mono"
              type="number"
              min="1"
              max="1000"
              @input="rd.setParam('rrf_k', Number(($event.target as HTMLInputElement).value))"
            />
          </AppField>
          <AppField label="score_threshold" :hint="`空 = 默认 ${rd.meta?.defaults?.score_threshold ?? 0}`">
            <input
              :value="rd.params.score_threshold ?? ''"
              class="c-input mono"
              type="number"
              step="0.01"
              min="0"
              max="1"
              placeholder="空 = 默认"
              @input="
                rd.setParam(
                  'score_threshold',
                  ($event.target as HTMLInputElement).value === ''
                    ? null
                    : Number(($event.target as HTMLInputElement).value),
                )
              "
            />
          </AppField>
        </div>

        <!-- prompt -->
        <AppField label="prompt">
          <textarea
            v-model="rd.query"
            class="c-textarea"
            rows="3"
            placeholder="最近总是内耗，怎么和自己和解"
            @keydown="onPromptKeydown"
          ></textarea>
        </AppField>

        <div class="rd-actions">
          <AppButton variant="primary" :loading="rd.running" :disabled="!rd.canRun" @click="onRun">
            运行检索
          </AppButton>
          <span class="rd-run-hint">
            {{ rd.hasAnySwitch ? 'Enter 换行 · Ctrl/⌘ + Enter 运行' : '至少选择一种检索方式' }}
          </span>
        </div>

        <p v-if="rd.error" class="rd-error">{{ rd.error }}</p>
      </section>

      <!-- ================= 排名迁移图 ================= -->
      <section class="rd-panel">
        <header class="rd-panel__head">
          <div class="rd-panel__title-row">
            <span class="rd-panel__title">排名迁移</span>
            <span class="rd-panel__hint">
              {{ rd.result ? '同一文档在各阶段的位次流动' : '运行后显示' }}
            </span>
          </div>
        </header>
        <RankShiftChart :data="rd.result" />
      </section>

      <!-- ================= 最终结果 ================= -->
      <section class="rd-panel rd-panel--accent">
        <header class="rd-panel__head">
          <div class="rd-panel__title-row">
            <span class="rd-panel__title">最终检索结果</span>
            <span class="rd-panel__hint">{{ finalHint }}</span>
          </div>
        </header>

        <AppSkeleton v-if="rd.running" variant="card" :lines="2" />

        <AppEmpty
          v-else-if="!finalResults.length"
          icon="search"
          :title="rd.result ? '本次没有最终结果' : '尚未运行'"
          :desc="rd.result ? '候选可能被阈值过滤或未命中' : '运行一次检索后展示 Top-K'"
        />

        <div v-else class="final-list">
          <div
            v-for="(item, i) in finalResults"
            :key="item.doc_id + i"
            class="final-card"
            role="button"
            tabindex="0"
            :aria-label="`阅读原文：${item.doc?.title || item.doc_id}`"
            @click="openDoc(item.doc_id)"
            @keydown.enter.prevent="openDoc(item.doc_id)"
            @keydown.space.prevent="openDoc(item.doc_id)"
          >
            <span class="final-card__no">{{ item.rank ?? i + 1 }}</span>
            <div class="final-card__body">
              <div class="final-card__top">
                <span class="final-card__title">{{ item.doc?.title || item.doc_id }}</span>
                <span v-if="item.doc?.doc_type" class="badge" :class="`badge--${item.doc.doc_type}`">
                  {{ item.doc.doc_type }}
                </span>
                <span v-if="item.doc?.date" class="badge badge--date">{{ item.doc.date }}</span>
                <span class="final-card__score tabular">{{ scoreText(item.score) }}</span>
              </div>
              <p class="final-card__sum">{{ item.doc?.summary || '（无摘要）' }}</p>
            </div>
          </div>
        </div>
      </section>

      <!-- ================= 逐阶段 ================= -->
      <section class="rd-panel">
        <header class="rd-panel__head">
          <div class="rd-panel__title-row">
            <span class="rd-panel__title">逐阶段候选</span>
            <span class="rd-panel__hint">{{ stageHint }}</span>
          </div>
        </header>

        <AppEmpty
          v-if="!stages.length"
          icon="list"
          :title="rd.result ? '本次未返回阶段结果' : '尚未运行'"
          desc="运行后按阶段展示召回候选与位次"
        />

        <div v-else class="stages">
          <AppDisclosure
            v-for="(stage, i) in stages"
            :key="stage.name"
            :label="stage.label || stage.name"
            :meta="`${stage.results?.length ?? 0} 候选`"
            :open="i === 0"
          >
            <template #meta>
              <span class="stage-tag">{{ stage.name }}</span>
              <span class="stage-lat tabular">{{ fmtDuration(stage.latency_ms) }}</span>
            </template>

            <div v-if="!stage.results?.length" class="rd-muted">该阶段无排名输出</div>

            <ol v-else class="ranks">
              <li
                v-for="(r, j) in stage.results"
                :key="r.doc_id + j"
                class="rank"
                :class="{ 'is-final': finalIdSet.has(String(r.doc_id)) }"
                role="button"
                tabindex="0"
                :aria-label="`阅读原文：${r.doc?.title || r.doc_id}`"
                @click="openDoc(r.doc_id)"
                @keydown.enter.prevent="openDoc(r.doc_id)"
              >
                <span class="rank__no tabular">#{{ r.rank ?? j + 1 }}</span>
                <span class="rank__score tabular">{{ scoreText(r.score) }}</span>
                <div class="rank__body">
                  <div class="rank__top">
                    <span class="rank__title">{{ r.doc?.title || r.doc_id }}</span>
                    <span v-if="r.doc?.doc_type" class="badge" :class="`badge--${r.doc.doc_type}`">
                      {{ r.doc.doc_type }}
                    </span>
                    <span v-if="finalIdSet.has(String(r.doc_id))" class="rank__final">最终</span>
                  </div>
                  <p class="rank__sum">{{ r.doc?.summary || '（无摘要）' }}</p>
                </div>
              </li>
            </ol>
          </AppDisclosure>
        </div>
      </section>

      <!-- ================= 运行摘要 + 日志 ================= -->
      <div class="rd-grid">
        <section class="rd-panel">
          <header class="rd-panel__head">
            <span class="rd-panel__title">查询改写</span>
          </header>

          <AppEmpty
            v-if="!rd.result"
            icon="compass"
            title="尚未运行"
            desc="运行后展示改写后的检索查询"
          />

          <dl v-else class="kv">
            <template v-if="optimized.search_query">
              <dt>search_query</dt>
              <dd>{{ optimized.search_query }}</dd>
            </template>
            <template v-if="optimized.match_topics?.length">
              <dt>match_topics</dt>
              <dd>
                <span v-for="t in optimized.match_topics" :key="t" class="chip chip--topic">{{ t }}</span>
              </dd>
            </template>
            <template v-if="optimized.keywords?.length">
              <dt>keywords</dt>
              <dd>
                <span v-for="t in optimized.keywords" :key="t" class="chip chip--kw">{{ t }}</span>
              </dd>
            </template>
            <template v-if="optimized.distinctive_terms?.length">
              <dt>distinctive</dt>
              <dd>
                <span v-for="t in optimized.distinctive_terms" :key="t" class="chip chip--dist">{{ t }}</span>
              </dd>
            </template>
            <template v-if="!optimized.search_query">
              <dt>—</dt>
              <dd class="rd-muted">本次未产出查询改写（可能未启用该阶段）</dd>
            </template>
          </dl>
        </section>

        <section class="rd-panel">
          <header class="rd-panel__head">
            <div class="rd-panel__title-row">
              <span class="rd-panel__title">检索日志</span>
              <span class="rd-panel__hint">{{ logs.length ? logs.length + ' 条' : '—' }}</span>
            </div>
          </header>

          <AppEmpty v-if="!logs.length" icon="pulse" title="尚无日志" desc="运行后展示各阶段细节" />

          <div v-else class="logs">
            <AppDisclosure
              v-for="(item, i) in logs"
              :key="i"
              :label="item.label || item.stage"
              :meta="fmtLogTime(item.timestamp)"
              :tone="item.is_error ? 'error' : 'default'"
              :has-detail="item.is_error || logRows(item).length > 0"
              :open="item.is_error"
              variant="line"
            >
              <template #meta>
                <span class="stage-tag">{{ item.stage }}</span>
              </template>

              <pre v-if="item.is_error" class="log-err">{{ item.error_msg || '未知错误' }}</pre>

              <dl v-if="logRows(item).length" class="kv kv--mono">
                <template v-for="[k, v] in logRows(item)" :key="k">
                  <dt>{{ k }}</dt>
                  <dd :class="{ 'is-json': isComplex(v) }">{{ formatValue(v) }}</dd>
                </template>
              </dl>
            </AppDisclosure>
          </div>
        </section>
      </div>

      <!-- ================= 全部文档 ================= -->
      <section class="rd-panel">
        <header class="rd-panel__head">
          <div class="rd-panel__title-row">
            <span class="rd-panel__title">全部文档</span>
            <span class="rd-panel__hint">
              总数 {{ rd.docTotal }} · daily {{ rd.docTypeCounts.daily }} · weekly {{ rd.docTypeCounts.weekly }}
              <template v-if="rd.filteredDocs.length !== rd.docs.length">
                · 当前 {{ rd.filteredDocs.length }}
              </template>
            </span>
          </div>
          <AppButton size="sm" icon="refresh" :loading="rd.docsLoading" @click="rd.loadDocs(newScope())">
            刷新
          </AppButton>
        </header>

        <div class="doc-filters">
          <input
            v-model="rd.docFilter"
            class="c-input"
            placeholder="按标题 / 摘要 / 正文 / 关键词过滤…"
            aria-label="按标题、摘要、正文或关键词过滤文档"
          />
          <select v-model="rd.docTypeFilter" class="c-select" aria-label="文档类型筛选">
            <option value="">全部类型</option>
            <option value="daily">daily · 日常</option>
            <option value="weekly">weekly · 周记</option>
          </select>
        </div>

        <AppSkeleton v-if="rd.docsLoading" variant="card" :lines="3" />

        <AppEmpty
          v-else-if="rd.docsError"
          icon="alert"
          tone="error"
          title="文档加载失败"
          :desc="rd.docsError"
        >
          <AppButton size="sm" variant="primary" icon="refresh" @click="rd.loadDocs(newScope())">
            重试
          </AppButton>
        </AppEmpty>

        <AppEmpty
          v-else-if="!rd.filteredDocs.length"
          icon="doc"
          :title="rd.docs.length ? '没有匹配的文档' : '暂无文档'"
          :desc="rd.docs.length ? '试试放宽过滤条件' : '先在「码字编辑」中记录内容并预处理'"
        />

        <div v-else class="doc-list">
          <AppDisclosure
            v-for="d in rd.filteredDocs"
            :key="d.doc_id"
            :label="d.title || d.doc_id"
            :meta="d.date || ''"
          >
            <template #meta>
              <span v-if="d.doc_type" class="badge" :class="`badge--${d.doc_type}`">{{ d.doc_type }}</span>
              <span class="doc-id">{{ d.doc_id }}</span>
            </template>

            <p class="doc-sum">{{ d.summary || '（无摘要）' }}</p>
            <div class="doc-chips">
              <span v-for="t in d.topic" :key="t" class="chip chip--topic">{{ t }}</span>
              <span v-for="t in d.keywords" :key="t" class="chip chip--kw">{{ t }}</span>
            </div>
            <pre v-if="d.doc_type === 'weekly'" class="doc-body">{{ d.problem }}\n\n{{ d.analysis }}\n\n{{ d.solution }}</pre>
            <pre v-else class="doc-body">{{ d.content }}</pre>
          </AppDisclosure>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.stats {
  display: flex;
  gap: var(--sp-2);
}

.stat {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 3px 10px;
  border-radius: var(--r-pill);
  border: 1px solid var(--border);
  background: var(--surface-raised);
}

.stat b {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  font-weight: var(--fw-medium);
  color: var(--accent-deep);
}

.stat i {
  font-style: normal;
  font-size: 10.5px;
  color: var(--text-tertiary);
}

.rd-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--sp-4) 2px var(--sp-6);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

/* ---------- 面板 ---------- */
.rd-panel {
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--surface-overlay);
  padding: var(--sp-4);
}

.rd-panel--accent {
  border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
}

.rd-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-bottom: var(--sp-3);
}

.rd-panel__title-row {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  flex-wrap: wrap;
  min-width: 0;
}

.rd-panel__title {
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
}

.rd-panel__hint {
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
  word-break: break-word;
}

/* ---------- 开关 ---------- */
.switches {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--sp-2);
}

.switch {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  background: var(--surface-raised);
  text-align: left;
  cursor: pointer;
  transition:
    border-color var(--dur-base) var(--ease-out),
    box-shadow var(--dur-base) var(--ease-out);
}

.switch:hover {
  border-color: var(--border-strong);
}

.switch.is-on {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--surface-accent-ghost);
}

.switch__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.switch__name {
  font-family: var(--font-serif);
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  color: var(--text-primary);
}

.switch__alias {
  margin-left: 5px;
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-style: normal;
  font-weight: var(--fw-regular);
  color: var(--text-tertiary);
}

.switch__desc {
  font-size: 10.5px;
  line-height: var(--lh-tight);
  color: var(--text-tertiary);
}

.switch__mark {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  margin-left: auto;
  border-radius: 50%;
  border: 1px solid var(--border);
  color: transparent;
}

.switch.is-on .switch__mark {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--text-on-accent);
}

/* ---------- 参数 ---------- */
.params {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--sp-3);
  margin: var(--sp-3) 0;
}

.mono {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.rd-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-top: var(--sp-3);
}

.rd-run-hint {
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

.rd-error {
  margin-top: var(--sp-2);
  padding: 6px 10px;
  border-radius: var(--r-sm);
  background: var(--surface-danger-ghost);
  color: var(--danger);
  font-size: var(--fs-xs);
}

/* ---------- 最终结果 ---------- */
.final-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.final-card {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr);
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-md);
  border: 1px solid color-mix(in srgb, var(--accent) 24%, transparent);
  background: color-mix(in srgb, var(--accent) 4%, transparent);
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

/* 结果卡可点开原文：hover 时给明确的可操作反馈 */
.final-card:hover {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  transform: translateY(-1px);
}

.final-card:hover .final-card__title {
  color: var(--accent-deep);
}

.final-card__no {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--text-on-accent);
  font-family: var(--font-mono);
  font-size: 11px;
}

.final-card__body {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.final-card__top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.final-card__title {
  font-family: var(--font-serif);
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  overflow-wrap: anywhere;
}

.final-card__score {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--accent-deep);
}

.final-card__sum {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  line-height: var(--lh-tight);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---------- 徽章 / chip ---------- */
.badge {
  padding: 1px 7px;
  border-radius: var(--r-sm);
  font-family: var(--font-mono);
  font-size: 10px;
  white-space: nowrap;
}

.badge--daily {
  background: rgba(78, 109, 106, 0.12);
  color: #3f5a57;
}

.badge--weekly {
  background: var(--surface-warning-ghost);
  color: var(--warning);
}

.badge--date {
  background: var(--surface-sunken);
  color: var(--text-tertiary);
}

.chip {
  display: inline-block;
  margin: 0 4px 3px 0;
  padding: 1px 7px;
  border-radius: var(--r-pill);
  font-size: 10.5px;
}

.chip--topic {
  background: var(--surface-accent-ghost);
  color: var(--accent-deep);
}

.chip--kw {
  background: rgba(78, 109, 106, 0.1);
  color: #3f5a57;
}

.chip--dist {
  background: var(--surface-warning-ghost);
  color: var(--warning);
}

/* ---------- 阶段 ---------- */
.stages {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.stage-tag {
  padding: 1px 7px;
  border-radius: var(--r-sm);
  background: var(--surface-sunken);
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-secondary);
}

.stage-lat {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-tertiary);
}

.ranks {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.rank {
  display: grid;
  grid-template-columns: 30px 58px minmax(0, 1fr);
  gap: 4px var(--sp-2);
  align-items: start;
  padding: var(--sp-1) var(--sp-2);
  border-radius: var(--r-sm);
  border: 1px solid transparent;
  background: var(--surface);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}

.rank:hover {
  background: var(--surface-sunken);
}

.rank:hover .rank__title {
  color: var(--accent-deep);
}

.rank.is-final {
  border-color: color-mix(in srgb, var(--accent) 28%, transparent);
  background: color-mix(in srgb, var(--accent) 4%, transparent);
}

.rank__no,
.rank__score {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding-top: 1px;
}

.rank__no {
  color: var(--text-tertiary);
}

.rank__score {
  color: var(--entity-document);
}

.rank__body {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rank__top {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  min-width: 0;
}

.rank__title {
  font-size: var(--fs-xs);
  font-weight: var(--fw-medium);
  color: var(--text-primary);
  overflow-wrap: anywhere;
}

.rank__final {
  padding: 0 5px;
  border-radius: var(--r-pill);
  background: var(--accent);
  color: var(--text-on-accent);
  font-family: var(--font-mono);
  font-size: 9.5px;
}

.rank__sum {
  font-size: 10.5px;
  color: var(--text-tertiary);
  line-height: var(--lh-tight);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.rd-muted {
  color: var(--text-tertiary);
  font-size: var(--fs-xs);
}

/* ---------- 双列 ---------- */
.rd-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-3);
  align-items: start;
}

/* ---------- KV ---------- */
.kv {
  display: grid;
  grid-template-columns: minmax(80px, 120px) minmax(0, 1fr);
  gap: 4px var(--sp-3);
  font-size: var(--fs-xs);
}

.kv dt {
  font-family: var(--font-mono);
  color: var(--accent-deep);
  word-break: break-word;
}

.kv dd {
  color: var(--text-secondary);
  word-break: break-word;
}

.kv--mono {
  font-family: var(--font-mono);
  font-size: 10.5px;
}

.kv dd.is-json {
  white-space: pre-wrap;
  background: var(--surface);
  padding: var(--sp-1) var(--sp-2);
  border-radius: var(--r-sm);
}

/* ---------- 日志 ---------- */
.logs {
  display: flex;
  flex-direction: column;
  gap: 1px;
  max-height: 380px;
  overflow-y: auto;
}

.log-err {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--danger);
  background: var(--surface-danger-ghost);
  padding: var(--sp-2);
  border-radius: var(--r-sm);
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---------- 文档 ---------- */
.doc-filters {
  display: flex;
  gap: var(--sp-2);
  margin-bottom: var(--sp-2);
  flex-wrap: wrap;
}

.doc-filters .c-input {
  flex: 1 1 200px;
  min-width: 0;
  font-size: var(--fs-xs);
}

.doc-filters .c-select {
  flex: 0 0 auto;
  font-size: var(--fs-xs);
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  max-height: 480px;
  overflow-y: auto;
}

.doc-id {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-disabled);
}

.doc-sum {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  line-height: var(--lh-tight);
  margin-bottom: var(--sp-1);
}

.doc-chips {
  margin-bottom: var(--sp-1);
}

.doc-body {
  font-family: var(--font-sans);
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--surface);
  padding: var(--sp-2);
  border-radius: var(--r-sm);
  max-height: 200px;
  overflow-y: auto;
}

/* ---------- 响应式 ---------- */
@media (max-width: 1180px) {
  .switches {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1100px) {
  .rd-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .switches,
  .params {
    grid-template-columns: 1fr;
  }

  .rank {
    grid-template-columns: 26px minmax(0, 1fr);
    grid-template-areas:
      'no score'
      'body body';
  }

  .rank__no {
    grid-area: no;
  }

  .rank__score {
    grid-area: score;
  }

  .rank__body {
    grid-area: body;
  }
}
</style>
