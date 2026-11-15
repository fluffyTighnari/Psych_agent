<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EditorState, Compartment } from '@codemirror/state'
import {
  EditorView,
  keymap,
  placeholder as cmPlaceholder,
  lineNumbers,
  drawSelection,
  highlightActiveLine,
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { markdown, markdownLanguage } from '@codemirror/lang-markdown'
import { syntaxHighlighting, HighlightStyle } from '@codemirror/language'
import { tags } from '@lezer/highlight'

/**
 * CodeMirror 6 封装。
 *
 * 为什么不用 textarea：中文输入法（IME）在长文本组合输入时有兼容问题，
 * 且无法做语法高亮与结构化装饰。CodeMirror 的 IME 处理成熟、体积可控（~120KB gzip）。
 *
 * v-model 双向同步的关键：用 lastEmitted 记录自己最后一次发出的值，
 * 外部 watch 到相同的值就跳过，否则会陷入「改→重置文档→触发 change→再改」的循环。
 */

const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    /** 只读（预览态用） */
    readonly?: boolean
    minHeight?: string
    autofocus?: boolean
  }>(),
  { placeholder: '', readonly: false, minHeight: '420px', autofocus: false },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  /** Ctrl/Cmd + S */
  save: []
  /** Ctrl/Cmd + Enter */
  submit: []
}>()

const hostRef = ref<HTMLElement | null>(null)
let view: EditorView | null = null
let lastEmitted = props.modelValue

/** 动态配置隔间：只读 / 主题变化时 reconfigure 而不重建实例 */
const readonlyCompartment = new Compartment()

/* ---------- 主题：与设计令牌对齐 ---------- */
function buildTheme() {
  const cs = getComputedStyle(document.documentElement)
  const v = (n: string, fb: string) => cs.getPropertyValue(n).trim() || fb

  return EditorView.theme(
    {
      '&': {
        /*
         * 字号必须读令牌，不能写死。
         * 写死 15px 时，它完全绕过 --density：界面整体缩到 75% 后，
         * 周边文字 11.6px、编辑器正文还是 15px，看上去"编辑框里的字特别大"。
         */
        fontSize: v('--fs-base', '15px'),
        backgroundColor: 'transparent',
        color: v('--text-primary', '#2a231c'),
        // 不写死 100%：高度由内容与 min-height 决定，滚动交给外层容器
        minHeight: 'inherit',
      },
      '.cm-scroller': {
        fontFamily: v('--font-sans', 'sans-serif'),
        lineHeight: '1.85',
        // 编辑器自身不产生滚动条，避免与外层滚动嵌套
        overflow: 'visible',
      },
      '.cm-content': {
        padding: '14px 16px',
        caretColor: v('--accent', '#c24a2e'),
      },
      '.cm-line': { padding: '0' },
      '&.cm-focused': { outline: 'none' },
      '.cm-placeholder': { color: v('--text-tertiary', '#746750') },
      '.cm-gutters': {
        backgroundColor: 'transparent',
        border: 'none',
        color: v('--text-disabled', '#a89a86'),
        fontFamily: v('--font-mono', 'monospace'),
        fontSize: v('--fs-2xs', '11px'),
      },
      '.cm-activeLine': { backgroundColor: 'rgba(194, 74, 46, 0.035)' },
      '.cm-activeLineGutter': { backgroundColor: 'transparent', color: v('--accent-deep', '#a03820') },
      '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': {
        backgroundColor: 'rgba(194, 74, 46, 0.14) !important',
      },
      '.cm-cursor': { borderLeftColor: v('--accent', '#c24a2e'), borderLeftWidth: '2px' },
    },
    { dark: false },
  )
}

function buildHighlight() {
  const cs = getComputedStyle(document.documentElement)
  const v = (n: string, fb: string) => cs.getPropertyValue(n).trim() || fb

  return syntaxHighlighting(
    HighlightStyle.define([
      { tag: tags.heading, fontWeight: '700', color: v('--text-primary', '#2a231c') },
      { tag: tags.strong, fontWeight: '700', color: v('--text-primary', '#2a231c') },
      { tag: tags.emphasis, fontStyle: 'italic' },
      { tag: tags.link, color: v('--accent-deep', '#a03820'), textDecoration: 'underline' },
      { tag: tags.monospace, fontFamily: v('--font-mono', 'monospace'), color: v('--accent-deep', '#a03820') },
      { tag: tags.quote, color: v('--text-secondary', '#6c5f4e'), fontStyle: 'italic' },
      { tag: tags.list, color: v('--accent', '#c24a2e') },
      { tag: tags.processingInstruction, color: v('--text-disabled', '#a89a86') },
    ]),
  )
}

function createState(doc: string, readonly: boolean) {
  return EditorState.create({
    doc,
    extensions: [
      lineNumbers(),
      history(),
      drawSelection(),
      highlightActiveLine(),
      markdown({ base: markdownLanguage }),
      buildHighlight(),
      buildTheme(),
      cmPlaceholder(props.placeholder),
      readonlyCompartment.of(EditorState.readOnly.of(readonly)),
      EditorView.lineWrapping,
      /*
       * CodeMirror 的 contenteditable 是 role=textbox，可访问名必须挂在它上面。
       * aria-label 放在宿主 div 上会被 axe 判为 aria-prohibited-attr
       * （div 无 role 时不允许用 aria-label）。
       */
      EditorView.contentAttributes.of({
        'aria-label': props.placeholder || 'Markdown 编辑器',
        'aria-multiline': 'true',
      }),
      EditorView.updateListener.of((update) => {
        if (!update.docChanged) return
        const value = update.state.doc.toString()
        // 记录自己发出的值，避免外部 watch 回环
        lastEmitted = value
        emit('update:modelValue', value)
      }),
      keymap.of([
        {
          key: 'Mod-s',
          preventDefault: true,
          run: () => {
            emit('save')
            return true
          },
        },
        {
          key: 'Mod-Enter',
          preventDefault: true,
          run: () => {
            emit('submit')
            return true
          },
        },
        ...defaultKeymap,
        ...historyKeymap,
        indentWithTab,
      ]),
    ],
  })
}

onMounted(() => {
  const host = hostRef.value
  if (!host) return

  view = new EditorView({
    state: createState(props.modelValue, props.readonly),
    parent: host,
  })

  if (props.autofocus) view.focus()
})

onBeforeUnmount(() => {
  view?.destroy()
  view = null
})

// 外部改值（如「从对话摘取」插入）：只在值确实不同时重置文档
watch(
  () => props.modelValue,
  (next) => {
    if (!view) return
    if (next === lastEmitted) return

    const current = view.state.doc.toString()
    if (next === current) return

    // 保留光标位置，避免插入内容后跳到文首
    const sel = view.state.selection.main
    view.dispatch({
      changes: { from: 0, to: current.length, insert: next },
      selection: { anchor: Math.min(sel.anchor, next.length) },
    })
    lastEmitted = next
  },
)

watch(
  () => props.readonly,
  (ro) => {
    view?.dispatch({ effects: readonlyCompartment.reconfigure(EditorState.readOnly.of(ro)) })
  },
)

/** 在光标处插入文本（摘取面板用） */
function insertAtCursor(text: string) {
  if (!view) return
  const sel = view.state.selection.main
  view.dispatch({
    changes: { from: sel.from, to: sel.to, insert: text },
    selection: { anchor: sel.from + text.length },
  })
  view.focus()
}

/** 追加到末尾 */
function appendText(text: string) {
  if (!view) return
  const end = view.state.doc.length
  const prefix = end > 0 && !view.state.doc.toString().endsWith('\n') ? '\n\n' : ''
  const insert = prefix + text
  view.dispatch({
    changes: { from: end, insert },
    selection: { anchor: end + insert.length },
  })
  view.focus()
}

function focus() {
  view?.focus()
}

defineExpose({ insertAtCursor, appendText, focus })
</script>

<template>
  <!-- 不用 aria-label：宿主是普通 div，挂 aria-label 违反 aria-prohibited-attr。
       可访问名由内部 .cm-content（role=textbox）通过 contentAttributes 提供。 -->
  <div ref="hostRef" class="md-editor" :style="{ '--editor-min-h': minHeight }"></div>
</template>

<style scoped>
.md-editor {
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--surface-raised);
  /*
   * 高度随内容增长，滚动交给页面；min-height 由 prop 控。
   *
   * overflow: hidden 只为了裁圆角，但它同时会吃掉超出的内容：
   * 长文档时 .cm-editor 长到 750px、外层停在 653px，超出的部分被裁掉，
   * 而 .app-view 的 scrollHeight 仍是 950 —— 页面表现为"写长了却滚不动"。
   * 改成 clip 之外的方案：不裁内容，让外层跟着长。
   */
  min-height: var(--editor-min-h, 420px);
  /* 圆角裁切交给 background-clip，不再依赖 overflow */
  background-clip: padding-box;
  /*
   * 焦点态不用朱砂色描边。
   * 试过的三种方案都失败：
   *   1. 3px 外扩 box-shadow  → 左侧一条贯穿的朱砂竖线；
   *   2. 整圈朱砂边框        → 变成显眼红框；
   *   3. 仅左缘 2px 朱砂线    → 仍然是那条红线，只是细了点。
   * 结论：正文编辑区不需要品牌色标记焦点 —— 光标本身已经足够指示。
   * 只用背景微提亮 + 边框加深，保持纸感的暖色层次。
   */
  transition:
    border-color var(--dur-base) var(--ease-out),
    background var(--dur-base) var(--ease-out);
}

.md-editor:focus-within {
  border-color: var(--border-strong);
  background: var(--surface-overlay);
}

.md-editor :deep(.cm-editor) {
  /*
   * 让编辑区至少铺满容器，但不钉死高度。
   *
   * 三代方案的取舍：
   *   ① `height: 100%` —— 把高度钉死，长文档被 overflow 裁掉、页面滚不动（批次 H 的坑）；
   *   ② `min-height: inherit` —— inherit 取的是父级的**声明值**（420px），
   *      不是父级被 flex 撑开后的实际高度，于是外层 653px、内层还是 420px，底部一片空白；
   *   ③ 现在：`min-height: 100%` —— 100% 相对父级的实际高度，短内容铺满、长内容自然增长。
   */
  min-height: 100%;
}
</style>
