// 图例用的字形预览：默认复用图谱渲染的同一份几何；
// 会话节点在画布上使用整枚轨道图形，图例则用同构的线稿缩略版，避免 14px 被填成一枚色点。
<script setup lang="ts">
import { computed } from 'vue'
import type { GraphNodeType } from '@/core/api/types'
import { glyphFor } from '@/core/graph/glyphs'

const props = withDefaults(
  defineProps<{
    type: GraphNodeType
    size?: number
  }>(),
  { size: 14 },
)

const glyph = computed(() => glyphFor(props.type))
</script>

<template>
  <svg
    class="nglyph"
    :class="`nglyph--${type}`"
    viewBox="0 0 48 48"
    :width="size"
    :height="size"
    aria-hidden="true"
  >
    <path
      v-for="(part, i) in glyph.parts"
      :key="i"
      :d="part.d"
      :transform="part.transform"
      :class="`nglyph__part nglyph__part--${part.role}`"
    />
    <circle
      v-for="(dot, i) in glyph.dots ?? []"
      :key="`dot-${i}`"
      :cx="dot.cx"
      :cy="dot.cy"
      :r="dot.r"
      :opacity="dot.opacity ?? 1"
      class="nglyph__dot"
    />
  </svg>
</template>

<style scoped>
.nglyph {
  display: block;
  overflow: visible;
  flex: 0 0 auto;
}

.nglyph--session {
  --ng-ink: var(--entity-session);
  --ng-soft: var(--entity-session-soft);
}
.nglyph--memory {
  --ng-ink: var(--entity-memory);
  --ng-soft: var(--entity-memory-soft);
}
.nglyph--document {
  --ng-ink: var(--entity-document);
  --ng-soft: var(--entity-document-soft);
}
.nglyph--reason {
  --ng-ink: var(--entity-reason);
  --ng-soft: var(--entity-reason-soft);
}

.nglyph__part {
  vector-effect: non-scaling-stroke;
  fill: none;
  stroke: var(--ng-ink);
  stroke-linecap: round;
  stroke-linejoin: round;
}

.nglyph__part--body {
  fill: var(--ng-soft);
  stroke-width: 1.4px;
}

.nglyph__part--ring {
  stroke-width: 1.4px;
}

.nglyph__part--orbit {
  stroke-width: 1.2px;
  opacity: 0.62;
}

.nglyph__part--trunk {
  stroke-width: 1.7px;
}

.nglyph__part--branch {
  stroke-width: 1.4px;
}

.nglyph__part--detail,
.nglyph__part--echo {
  stroke-width: 1px;
  opacity: 0.45;
}

.nglyph__part--leaf {
  fill: var(--ng-soft);
  stroke-width: 1px;
}

.nglyph__part--vein {
  stroke-width: 0.8px;
  opacity: 0.3;
}

.nglyph__part--trail {
  stroke-width: 1.2px;
  opacity: 0.38;
  stroke-dasharray: 3 3;
}

.nglyph__part--fold {
  fill: var(--ng-ink);
  fill-opacity: 0.1;
  stroke-width: 1px;
}

.nglyph__part--faint {
  stroke-width: 1px;
  opacity: 0.35;
}

.nglyph__dot {
  fill: var(--ng-ink);
}
</style>
