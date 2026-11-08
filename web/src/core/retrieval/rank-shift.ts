import type { RetrievalDebugResp, RetrievalRankItem, RetrievalStage } from '@/core/api/types'

/**
 * 排名迁移模型。
 *
 * 目的：回答「重排到底有没有用」这个检索调试的核心问题。
 * 当前要人肉在四个折叠面板间比对位次，一图即可看清同一文档的位次流动。
 *
 * 这个模块只做数据变换，不涉及绘制 —— 便于单测。
 */

export type TrackStatus = 'final' | 'dropped' | 'appeared'

export interface RankPoint {
  /** 列索引（对应 columns 中的阶段） */
  column: number
  /** 该阶段的位次（从 0 开始） */
  rank: number
  /** 该阶段的分数；未知为 null */
  score: number | null
}

export interface RankTrack {
  docId: string
  title: string
  docType: string
  status: TrackStatus
  /** 按列索引排列的点；缺失的列表示该阶段未召回 */
  points: RankPoint[]
  /** 首次出现的列 */
  firstColumn: number
  /** 最后一次出现的列 */
  lastColumn: number
}

export interface RankColumn {
  /** 阶段名（dense / bm25 / rrf / rerank …）或 'final' */
  key: string
  label: string
  /** 该列的候选数 */
  count: number
  latencyMs?: number
}

export interface RankShiftModel {
  columns: RankColumn[]
  tracks: RankTrack[]
  /** 每列的最大位次（决定纵轴刻度） */
  maxRank: number
  /** 进入最终结果的 track 数 */
  finalCount: number
}

const STAGE_LABELS: Record<string, string> = {
  optimize_prompt: '查询改写',
  dense: 'Dense 向量',
  bm25: 'BM25 关键词',
  rrf: 'RRF 融合',
  rerank: '重排',
  final: '最终结果',
}

function stageLabel(s: RetrievalStage): string {
  return s.label || STAGE_LABELS[s.name] || s.name
}

function docTitle(item: RetrievalRankItem): string {
  return item.doc?.title || item.doc_id || '—'
}

function docType(item: RetrievalRankItem): string {
  return (item.doc?.doc_type as string) || ''
}

/**
 * 从检索调试响应构建迁移模型。
 *
 * 列 = 实际执行的阶段（按 enabled_pipeline 顺序）+ final；
 * 行 = 所有出现过的 doc_id 并集；
 * 点 = 该 doc 在该阶段的 rank 与 score。
 */
export function buildRankShiftModel(resp: RetrievalDebugResp): RankShiftModel {
  const allStages = Array.isArray(resp.stages) ? resp.stages : []

  /*
   * 只保留有排名输出的阶段作为列。
   * optimize_prompt（查询改写）只产出改写后的查询文本、没有候选排名，
   * 给它一列会是一个空列，让位次图出现无意义的断点。
   * 该阶段的结果已在「查询改写」面板单独展示。
   */
  const stages = allStages.filter((s) => Array.isArray(s.results) && s.results.length > 0)

  // ---- 列 ----
  const columns: RankColumn[] = stages.map((s) => ({
    key: s.name,
    label: stageLabel(s),
    count: Array.isArray(s.results) ? s.results.length : 0,
    // exactOptionalPropertyTypes 关闭，可显式赋 undefined
    latencyMs: typeof s.latency_ms === 'number' ? s.latency_ms : undefined,
  }))

  const finalIds = new Set<string>(
    [
      ...(Array.isArray(resp.final?.doc_ids) ? resp.final.doc_ids : []),
      ...(Array.isArray(resp.final?.results) ? resp.final.results.map((r) => r.doc_id) : []),
    ].filter(Boolean),
  )

  const finalResults = Array.isArray(resp.final?.results) ? resp.final.results : []
  columns.push({
    key: 'final',
    label: STAGE_LABELS.final!,
    count: finalIds.size,
  })

  // ---- 轨迹 ----
  const byDoc = new Map<string, RankTrack>()
  let maxRank = 0

  stages.forEach((stage, colIdx) => {
    const results = Array.isArray(stage.results) ? stage.results : []
    results.forEach((item, i) => {
      const id = String(item.doc_id ?? '')
      if (!id) return

      const rank = typeof item.rank === 'number' ? item.rank - 1 : i
      if (rank > maxRank) maxRank = rank

      let track = byDoc.get(id)
      if (!track) {
        track = {
          docId: id,
          title: docTitle(item),
          docType: docType(item),
          status: 'dropped',
          points: [],
          firstColumn: colIdx,
          lastColumn: colIdx,
        }
        byDoc.set(id, track)
      }
      track.points.push({
        column: colIdx,
        rank,
        score: typeof item.score === 'number' ? item.score : null,
      })
      track.lastColumn = colIdx
    })
  })

  // final 列
  const finalColIdx = stages.length
  finalResults.forEach((item, i) => {
    const id = String(item.doc_id ?? '')
    if (!id) return
    const rank = typeof item.rank === 'number' ? item.rank - 1 : i
    let track = byDoc.get(id)
    if (!track) {
      track = {
        docId: id,
        title: docTitle(item),
        docType: docType(item),
        status: 'final',
        points: [],
        firstColumn: finalColIdx,
        lastColumn: finalColIdx,
      }
      byDoc.set(id, track)
    }
    track.points.push({
      column: finalColIdx,
      rank,
      score: typeof item.score === 'number' ? item.score : null,
    })
    track.lastColumn = finalColIdx
  })

  // ---- 状态判定 ----
  for (const track of byDoc.values()) {
    if (finalIds.has(track.docId)) {
      track.status = 'final'
    } else if (track.firstColumn > 0) {
      // 首列之外的阶段才出现 → 被某条召回链路新引入
      track.status = 'appeared'
    } else {
      track.status = 'dropped'
    }
  }

  // 排序：进入最终的在前，再按最终位次；其余按首次出现列 + 位次
  const tracks = [...byDoc.values()].sort((a, b) => {
    const aFinal = a.points.find((p) => p.column === finalColIdx)
    const bFinal = b.points.find((p) => p.column === finalColIdx)

    if (aFinal && bFinal) return aFinal.rank - bFinal.rank
    if (aFinal) return -1
    if (bFinal) return 1

    const aFirst = a.points[0]
    const bFirst = b.points[0]
    if (aFirst && bFirst && aFirst.column !== bFirst.column) return aFirst.column - bFirst.column
    return (aFirst?.rank ?? 0) - (bFirst?.rank ?? 0)
  })

  return {
    columns,
    tracks,
    maxRank: Math.max(maxRank, 1),
    finalCount: finalIds.size,
  }
}

/** 某 track 是否在某列有数据 */
export function pointAt(track: RankTrack, column: number): RankPoint | null {
  return track.points.find((p) => p.column === column) ?? null
}

/** 位次变化方向（用于文字摘要：升了还是降了） */
export function rankDelta(track: RankTrack): number | null {
  const first = track.points[0]
  const last = track.points[track.points.length - 1]
  if (!first || !last || first.column === last.column) return null
  // 位次数字变小 = 排名靠前 = 提升
  return first.rank - last.rank
}

/** 给屏幕阅读器/等价表格用的行摘要 */
export function trackSummary(track: RankTrack): string {
  const statusText =
    track.status === 'final' ? '进入最终结果' : track.status === 'appeared' ? '后期召回' : '被淘汰'
  const path = track.points.map((p) => `#${p.rank + 1}`).join(' → ')
  return `${track.title}：${path}（${statusText}）`
}
