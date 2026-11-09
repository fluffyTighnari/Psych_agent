<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import ViewHeader from '@/components/layout/ViewHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppConfirm from '@/components/ui/AppConfirm.vue'
import AppModal from '@/components/ui/AppModal.vue'
import AppField from '@/components/ui/AppField.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppPill from '@/components/ui/AppPill.vue'
import MarkdownEditor from '@/components/writer/MarkdownEditor.vue'
import PickFromChat from '@/components/writer/PickFromChat.vue'
import RichText from '@/components/chat/RichText.vue'
import { toastErr, toastInfo, toastOk } from '@/components/ui/useToast'
import { dataApi, toolApi } from '@/core/api'
import { createRequestScope } from '@/core/api/client'
import { useUiStore } from '@/stores/ui'
import { useWriteStore } from '@/stores/write'

const write = useWriteStore()
const ui = useUiStore()

const editorRef = ref<InstanceType<typeof MarkdownEditor> | null>(null)
const pickOpen = ref(false)
/** 从哪一段触发的摘取（决定面板默认插入目标） */
const pickTarget = ref<'problem' | 'analysis' | 'solution'>('problem')

function openPick(section?: 'problem' | 'analysis' | 'solution') {
  pickTarget.value = section ?? 'problem'
  pickOpen.value = true
}
const previewOpen = ref(false)
const preprocessing = ref(false)

let scope = createRequestScope()

/* ---------- 已存在的文件名（覆盖警告） ---------- */

const existingNames = ref<Set<string>>(new Set())

async function loadExisting() {
  try {
    const docs = await dataApi.knowledgeAll({ signal: scope.signal })
    existingNames.value = new Set(docs.map((d) => `${d.title || ''}|${d.date || ''}`))
  } catch {
    // 读取失败不影响写作，只是没有覆盖提示
  }
}

onMounted(async () => {
  const restored = write.restoreDraft()
  if (restored) toastInfo('已恢复上次未保存的草稿', 3000)
  await loadExisting()
})

onBeforeUnmount(() => {
  // 离开视图前立即落盘（保存成功时 store 内部会清除草稿）
  write.persistDraft()
  scope.abort()
})

/* ---------- 状态条 ---------- */

/**
 * 保存语义拆分（三层，用户需要能区分）：
 *   草稿  → localStorage，2s 防抖自动写，换浏览器会丢
 *   落盘  → data/notes/*.md，点「保存到笔记」才写
 *   入库  → 预处理后进入向量库/BM25，未预处理则检索不到
 *
 * 之前只说「已保存」，用户会误以为马上能检索到。
 */
const draftText = computed(() => {
  if (!write.draftSavedAt) return ''
  return new Date(write.draftSavedAt).toLocaleTimeString('zh-CN', { hour12: false })
})

const savedText = computed(() => {
  if (!write.lastSavedAt) return ''
  return new Date(write.lastSavedAt).toLocaleTimeString('zh-CN', { hour12: false })
})

/** 落盘后是否已入库（用最近一次预处理时刻粗判） */
const needsPreprocess = computed(() => {
  if (!write.lastSavedAt) return false
  if (!write.lastPreprocessedAt) return true
  return write.lastSavedAt > write.lastPreprocessedAt
})

/* ---------- Weekly 三段 ---------- */

const weeklySections = computed(() => [
  { key: 'problem' as const, n: 1, name: 'problem · 问题', hint: '发生了什么？具体在什么情境下？' },
  { key: 'analysis' as const, n: 2, name: 'analysis · 分析', hint: '你当时的假设是什么？它经得起检验吗？' },
  { key: 'solution' as const, n: 3, name: 'solution · 方案', hint: '你验证有效的最小动作是什么？' },
])

/* ---------- 预览 ---------- */

/** 预览用的完整 Markdown（与后端落盘格式一致） */
const previewMarkdown = computed(() => {
  if (write.mode === 'daily') return write.content
  return `### ${write.title}\n\n#### problem\n${write.problem}\n\n#### analysis\n${write.analysis}\n\n#### solution\n${write.solution}`
})

/* ---------- 保存 ---------- */

type PendingAction = 'save' | null
const pendingAction = ref<PendingAction>(null)
const confirming = ref(false)

/** 覆盖检测：同名文件已存在时提示 */
const wouldOverwrite = computed(() => {
  if (write.mode === 'daily') {
    const name = write.date ? `${write.date.split('-')[0]}-${Number(write.date.split('-')[1])}-${Number(write.date.split('-')[2])}` : ''
    return name ? [...existingNames.value].some((k) => k.endsWith(`|${name}`)) : false
  }
  return write.title ? [...existingNames.value].some((k) => k.startsWith(`${write.title}|`)) : false
})

async function onSave() {
  if (!write.canSave) {
    toastErr(write.mode === 'daily' ? '正文不能为空' : '请填写文件名、标题与至少一段内容')
    return
  }
  if (wouldOverwrite.value) {
    pendingAction.value = 'save'
    return
  }
  await doSave()
}

async function doSave() {
  confirming.value = true
  try {
    const res = write.mode === 'daily' ? await write.saveDaily() : await write.saveWeekly()
    /*
     * 措辞点明「已落盘但未入库」：用户需要知道此刻还检索不到，
     * 而不是以为保存完就生效了。
     */
    toastOk(`已写入 ${res.file_name} · 尚未进入知识库`, 8000, {
      label: '立即预处理',
      handler: () => void onPreprocess(),
    })
    await loadExisting()
  } catch (e) {
    toastErr('保存失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    confirming.value = false
    pendingAction.value = null
  }
}

async function onPreprocess() {
  preprocessing.value = true
  try {
    await toolApi.preprocess({ signal: scope.signal })
    write.lastPreprocessedAt = Date.now()
    toastOk('预处理完成 · 新内容已可被检索', 5000)
    await loadExisting()
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    toastErr('预处理失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    preprocessing.value = false
  }
}

function onClear() {
  write.clearAll()
  nextTick(() => editorRef.value?.focus())
}

function onPickInsertDone() {
  // 摘取后自动切到 weekly；无需额外处理，store 已更新
}

/* ---------- 键盘 ---------- */

function onSaveShortcut() {
  void onSave()
}

function onSubmitShortcut() {
  void onSave()
}
</script>

<template>
  <div class="app-view" :class="{ 'is-focus-mode': ui.focusMode }">
    <ViewHeader v-if="!ui.focusMode">
      <template #actions>
        <div class="modes" role="group" aria-label="写作模式">
          <AppPill :active="write.mode === 'daily'" @click="write.mode = 'daily'">
            Daily · 日常
          </AppPill>
          <AppPill :active="write.mode === 'weekly'" @click="write.mode = 'weekly'">
            Weekly · 周记
          </AppPill>
        </div>
        <AppButton size="sm" icon="list" @click="openPick()">从对话摘取</AppButton>
        <AppButton size="sm" icon="zoom-in" @click="ui.setFocusMode(true)">专注</AppButton>
      </template>
    </ViewHeader>

    <!-- 专注模式顶栏 -->
    <div v-if="ui.focusMode" class="focus-bar">
      <AppButton size="sm" variant="quiet" icon="close" @click="ui.setFocusMode(false)">退出专注</AppButton>

      <span class="focus-bar__stat tabular">{{ write.charCount }} 字</span>

      <AppButton
        size="sm"
        variant="primary"
        :loading="write.saving"
        :disabled="!write.canSave"
        @click="onSave"
      >
        保存到笔记
      </AppButton>
    </div>

    <!-- 元信息条 -->
    <div class="meta-bar" role="status" aria-live="polite">
      <span class="meta-bar__stat tabular">{{ write.charCount }} 字</span>
      <span class="meta-bar__sep" aria-hidden="true">·</span>
      <span class="meta-bar__stat">约 {{ write.readingMinutes }} 分钟</span>
      <span class="meta-bar__sep" aria-hidden="true">·</span>
      <!--
        持久化状态移到下方操作栏（与「保存到笔记」按钮同处），
        这一行只保留纯量化的写作信息 —— 同一屏不再出现两处状态。
      -->
      <span v-if="wouldOverwrite" class="meta-bar__warn">
        <AppIcon name="alert" :size="11" />
        同名文件已存在，保存会覆盖
      </span>
      <span v-if="write.mode === 'weekly'" class="meta-bar__fill">填写 {{ write.weeklyFilled }}/3</span>
      <span v-if="wouldOverwrite" class="meta-bar__warn">
        <AppIcon name="alert" :size="11" />
        同名文件已存在，保存会覆盖
      </span>
    </div>

    <!-- ============ Daily ============ -->
    <div v-if="write.mode === 'daily'" class="editor-wrap" :class="{ 'is-focus': ui.focusMode }">
      <AppField v-if="!ui.focusMode" label="日期" hint="文件名自动生成为 年.月.日.md；留空则由后端按今天生成">
        <input v-model="write.date" class="c-input date-input" type="date" />
      </AppField>

      <MarkdownEditor
        ref="editorRef"
        v-model="write.content"
        :min-height="ui.focusMode ? '72vh' : '420px'"
        placeholder="今天发生了什么，此刻的感受如何…"
        :autofocus="true"
        @save="onSaveShortcut"
        @submit="onSubmitShortcut"
      />
    </div>

    <!-- ============ Weekly ============ -->
    <div v-else class="editor-wrap" :class="{ 'is-focus': ui.focusMode }">
      <div v-if="!ui.focusMode" class="weekly-meta">
        <AppField label="文件名（用核心问题命名）">
          <input v-model="write.filename" class="c-input" placeholder="例如：如何停止过度在意他人评价" />
        </AppField>
        <AppField label="标题">
          <input v-model="write.title" class="c-input" placeholder="本周复盘主题" />
        </AppField>
      </div>

      <div class="weekly-sections">
        <section v-for="s in weeklySections" :key="s.key" class="weekly-sec">
          <header class="weekly-sec__head">
            <span class="weekly-sec__num" aria-hidden="true">{{ s.n }}</span>
            <span class="weekly-sec__name">{{ s.name }}</span>
            <span class="weekly-sec__state" :class="{ 'is-filled': !!write[s.key].trim() }">
              {{ write[s.key].trim() ? '已填写' : '未填写' }}
            </span>
            <button
              v-if="!write[s.key].trim()"
              type="button"
              class="weekly-sec__pick"
              @click="openPick(s.key)"
            >
              <AppIcon name="plus" :size="10" />
              从对话摘取
            </button>
          </header>

          <MarkdownEditor
            v-if="s.key === 'solution' && !ui.focusMode"
            ref="editorRef"
            v-model="write[s.key]"
            :min-height="'160px'"
            :placeholder="s.hint"
            @save="onSaveShortcut"
          />
          <MarkdownEditor
            v-else
            v-model="write[s.key]"
            :min-height="ui.focusMode ? '34vh' : '160px'"
            :placeholder="s.hint"
            @save="onSaveShortcut"
          />
        </section>
      </div>
    </div>

    <!-- 底部操作 -->
    <div class="actions">
      <AppButton variant="primary" :loading="write.saving" :disabled="!write.canSave" @click="onSave">
        保存到笔记
      </AppButton>

      <!--
        三态明确区分（唯一一处）：
          未持久化 → 内容只在内存/草稿，关浏览器会丢
          已持久化 → 已写入 .md 文件
          已入库   → 预处理完成，可被检索
      -->
      <span
        class="actions__state"
        :class="!write.isDirty ? 'is-dim' : write.isPersisted ? 'is-saved' : 'is-pending'"
      >
        <AppIcon
          :name="!write.isDirty ? 'pen' : write.isPersisted ? 'check' : 'alert'"
          :size="11"
        />
        {{
          !write.isDirty
            ? '尚未填写'
            : write.isPersisted
              ? `已持久化 ${savedText}`
              : '未持久化 · 仅存于草稿'
        }}
      </span>
      <span
        v-if="write.isDirty && !write.isPersisted && draftText"
        class="actions__state is-dim"
      >
        草稿 {{ draftText }}
      </span>
      <span v-if="needsPreprocess" class="actions__warn">
        <AppIcon name="alert" :size="11" />
        未进入知识库
      </span>
      <AppButton variant="ghost" :disabled="!write.isDirty" @click="onClear">清空</AppButton>
      <AppButton variant="quiet" icon="doc" @click="previewOpen = true">预览</AppButton>
      <AppButton
        v-if="!ui.focusMode"
        variant="quiet"
        icon="refresh"
        :loading="preprocessing"
        @click="onPreprocess"
      >
        预处理
      </AppButton>
      <span class="actions__hint">⌘/Ctrl + S 保存</span>
    </div>

    <!-- 从对话摘取 -->
    <PickFromChat :open="pickOpen" :initial-target="pickTarget" @close="(pickOpen = false), onPickInsertDone()" />

    <!-- 预览：用与对话一致的 RichText 渲染 -->
    <AppModal :open="previewOpen" title="预览（保存后的 Markdown）" width="680px" @close="previewOpen = false">
      <div class="preview">
        <RichText :text="previewMarkdown" :interactive="false" />
      </div>
      <template #foot>
        <AppButton variant="ghost" @click="previewOpen = false">关闭</AppButton>
      </template>
    </AppModal>

    <!-- 覆盖确认 -->
    <AppConfirm
      :open="pendingAction === 'save'"
      title="覆盖同名文件？"
      message="该日期 / 标题已存在文档。保存会直接覆盖原文件，没有版本历史，覆盖后无法恢复。"
      confirm-label="仍然覆盖"
      :danger="true"
      :loading="confirming"
      @confirm="doSave"
      @cancel="pendingAction = null"
    />
  </div>
</template>

<style scoped>
/*
 * 编辑页是内容型视图：整页滚动。
 * 之前只有 .editor-wrap 内部滚动，专注模式下它 overflow:visible，
 * 结果文字超出视口后既不能整页滚也不能内部滚 —— 内容被直接裁掉。
 */
.app-view {
  overflow-y: auto;
}

.modes {
  display: flex;
  gap: var(--sp-2);
}

/* ---------- 专注模式 ---------- */
/*
 * 专注模式：导航栏已被 App.vue 隐藏，这里去掉横向大内边距，
 * 让 76ch 的正文真正落在视口正中。
 */
.is-focus-mode {
  padding: var(--sp-3) var(--sp-3) var(--sp-4);
  align-items: center;
}

/* 专注模式下的顶栏与底部操作跟随正文宽度，而不是铺满整屏 */
.is-focus-mode .focus-bar,
.is-focus-mode .meta-bar,
.is-focus-mode .actions {
  max-width: 92ch;
  width: 100%;
  margin-inline: auto;
}

.focus-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding-bottom: var(--sp-2);
  flex: 0 0 auto;
}

.focus-bar__stat {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

.focus-bar__state {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-2xs);
  padding: 2px 8px;
  border-radius: var(--r-pill);
}

.focus-bar__state.is-saved {
  background: color-mix(in srgb, var(--success) 12%, transparent);
  color: var(--success);
}

.focus-bar__state.is-pending {
  background: var(--surface-warning-ghost);
  color: var(--warning);
}

.focus-bar__state.is-dim {
  color: var(--text-tertiary);
}

/* ---------- 元信息 ---------- */
/*
 * 「9 字 · 约 1 分钟 · 填写 2/3」是可读的中文状态句，不是 ID 或表格数据。
 * 原先整条塞进等宽栈 + 12.5px 三级灰，是这一页最难看清的一行。
 * 改用正文字体、次要色，与页头副标题同档；纯数字仍走 .tabular 保持对位。
 */
.meta-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  margin: var(--sp-3) 0 var(--sp-4);
  font-family: var(--font-sans);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  flex: 0 0 auto;
}

.meta-bar__sep {
  color: var(--text-disabled);
}

.meta-bar__state {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-tertiary);
}

.meta-bar__state.is-active {
  color: var(--text-secondary);
}

.meta-bar__state.is-saved {
  color: var(--success);
}

.meta-bar__state.is-pending {
  color: var(--warning);
}

.meta-bar__state.is-dim {
  color: var(--text-disabled);
}

.meta-bar__fill {
  padding: 1px 9px;
  border-radius: var(--r-pill);
  background: var(--surface-sunken);
  color: var(--text-secondary);
}

.meta-bar__warn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  padding: 1px 9px;
  border-radius: var(--r-pill);
  background: var(--surface-warning-ghost);
  color: var(--warning);
}

/* ---------- 编辑区 ---------- */
/*
 * 编辑区不自己滚，滚动交给 .app-view（整页）。
 * 双层滚动会让鼠标滚轮行为取决于光标位置，体验割裂。
 */
.editor-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  /* 编辑区居中并放宽：原来 1000px 左对齐，大屏右侧留白明显 */
  max-width: 1200px;
  width: 100%;
  margin-inline: auto;
  /* 底部留白收紧：原来 padding-bottom + actions 的 padding-top 叠加出大片空白 */
  padding-bottom: 0;
}

/* 专注模式：单栏但不必过窄，92ch 约 780px，比 76ch 少留很多空白 */
.editor-wrap.is-focus {
  max-width: 92ch;
  margin-inline: auto;
  width: 100%;
  /* 专注时由整页滚动，容器自身不滚也不裁切 */
  overflow: visible;
  min-height: auto;
}

/* Weekly 三段在专注模式下放宽行距，便于长文阅读 */
.editor-wrap.is-focus :deep(.cm-scroller) {
  line-height: 1.95;
}

.date-input {
  max-width: 240px;
}

.weekly-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4);
}

.weekly-sections {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.weekly-sec {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.weekly-sec__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.weekly-sec__num {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--surface-inverse);
  color: var(--text-on-dark);
  font-family: var(--font-serif);
  font-size: var(--fs-2xs);
}

.weekly-sec__name {
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  color: var(--text-primary);
}

.weekly-sec__state {
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

.weekly-sec__state.is-filled {
  color: var(--success);
}

.weekly-sec__pick {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: var(--r-pill);
  border: 1px dashed var(--border);
  background: transparent;
  color: var(--accent-deep);
  font-size: var(--fs-2xs);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}

.weekly-sec__pick:hover {
  background: var(--surface-accent-ghost);
}

/* ---------- 底部 ---------- */
.actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  flex: 0 0 auto;
  margin-top: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px solid var(--border-soft);
}

.actions__state {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

.actions__state.is-pending {
  color: var(--warning);
}

.actions__state.is-saved {
  color: var(--success);
}

.actions__state.is-dim {
  color: var(--text-disabled);
}

.actions__warn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: var(--r-pill);
  background: var(--surface-warning-ghost);
  color: var(--warning);
  font-size: var(--fs-2xs);
}

.actions__hint {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  color: var(--text-tertiary);
}

/* ---------- 预览 ---------- */
.preview {
  max-height: 60vh;
  overflow-y: auto;
  padding: var(--sp-2) 0 var(--sp-4);
}

@media (max-width: 720px) {
  .weekly-meta {
    grid-template-columns: 1fr;
  }

  .actions__hint {
    display: none;
  }
}
</style>
