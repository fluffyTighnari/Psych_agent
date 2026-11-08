/**
 * 排名迁移模型单测。
 * 复刻核心逻辑（与 rank-shift.ts 一致），验证：
 * 列构建、轨迹归并、final/appeared/dropped 三态判定、排序。
 */
let pass = 0, fail = 0
const eq = (a, e, label) => {
  const ok = JSON.stringify(a) === JSON.stringify(e)
  if (ok) { pass++; console.log(`PASS  ${label}`) }
  else { fail++; console.log(`FAIL  ${label}\n   expected ${JSON.stringify(e)}\n   actual   ${JSON.stringify(a)}`) }
}

function buildModel(resp) {
  const stages = resp.stages ?? []
  const columns = stages.map(s => ({ key: s.name, count: (s.results ?? []).length }))
  const finalIds = new Set([
    ...(resp.final?.doc_ids ?? []),
    ...(resp.final?.results ?? []).map(r => r.doc_id),
  ].filter(Boolean))
  const finalResults = resp.final?.results ?? []
  columns.push({ key: 'final', count: finalIds.size })

  const byDoc = new Map()
  stages.forEach((stage, colIdx) => {
    (stage.results ?? []).forEach((item, i) => {
      const id = String(item.doc_id ?? '')
      if (!id) return
      const rank = typeof item.rank === 'number' ? item.rank - 1 : i
      let t = byDoc.get(id)
      if (!t) { t = { docId: id, status: 'dropped', points: [], firstColumn: colIdx, lastColumn: colIdx }; byDoc.set(id, t) }
      t.points.push({ column: colIdx, rank })
      t.lastColumn = colIdx
    })
  })
  const finalColIdx = stages.length
  finalResults.forEach((item, i) => {
    const id = String(item.doc_id ?? '')
    if (!id) return
    const rank = typeof item.rank === 'number' ? item.rank - 1 : i
    let t = byDoc.get(id)
    if (!t) { t = { docId: id, status: 'final', points: [], firstColumn: finalColIdx, lastColumn: finalColIdx }; byDoc.set(id, t) }
    t.points.push({ column: finalColIdx, rank })
    t.lastColumn = finalColIdx
  })
  for (const t of byDoc.values()) {
    if (finalIds.has(t.docId)) t.status = 'final'
    else if (t.firstColumn > 0) t.status = 'appeared'
    else t.status = 'dropped'
  }
  const tracks = [...byDoc.values()].sort((a, b) => {
    const af = a.points.find(p => p.column === finalColIdx)
    const bf = b.points.find(p => p.column === finalColIdx)
    if (af && bf) return af.rank - bf.rank
    if (af) return -1
    if (bf) return 1
    const a0 = a.points[0], b0 = b.points[0]
    if (a0 && b0 && a0.column !== b0.column) return a0.column - b0.column
    return (a0?.rank ?? 0) - (b0?.rank ?? 0)
  })
  return { columns, tracks, finalCount: finalIds.size }
}

/* ---- 场景 1：标准四阶段，doc A 全程第一并进入最终 ---- */
const resp1 = {
  stages: [
    { name: 'dense',  results: [{ doc_id: 'A', rank: 1 }, { doc_id: 'B', rank: 2 }, { doc_id: 'C', rank: 3 }] },
    { name: 'bm25',   results: [{ doc_id: 'A', rank: 1 }, { doc_id: 'C', rank: 2 }] },
    { name: 'rrf',    results: [{ doc_id: 'A', rank: 1 }, { doc_id: 'C', rank: 2 }, { doc_id: 'B', rank: 3 }] },
    { name: 'rerank', results: [{ doc_id: 'A', rank: 1 }, { doc_id: 'C', rank: 2 }] },
  ],
  final: { doc_ids: ['A', 'C'], results: [{ doc_id: 'A', rank: 1 }, { doc_id: 'C', rank: 2 }] },
}
const m1 = buildModel(resp1)
eq(m1.columns.map(c => c.key), ['dense', 'bm25', 'rrf', 'rerank', 'final'], '列包含全部阶段 + final')
eq(m1.finalCount, 2, '最终结果 2 条')
eq(m1.tracks.map(t => [t.docId, t.status]), [['A', 'final'], ['C', 'final'], ['B', 'dropped']], 'A/C 进入最终，B 被淘汰')
eq(m1.tracks[0].points.map(p => p.rank), [0, 0, 0, 0, 0], 'A 全程第一')
eq(m1.tracks[1].points.map(p => p.rank), [2, 1, 1, 1, 1], 'C 从第 3 升到第 2')

/* ---- 场景 2：只在后续阶段出现（新召回） ---- */
const resp2 = {
  stages: [
    { name: 'dense',  results: [{ doc_id: 'A', rank: 1 }] },
    { name: 'bm25',   results: [{ doc_id: 'A', rank: 1 }, { doc_id: 'X', rank: 2 }] },
  ],
  final: { doc_ids: ['X'], results: [{ doc_id: 'X', rank: 1 }] },
}
const m2 = buildModel(resp2)
eq(m2.tracks.find(t => t.docId === 'X').status, 'final', 'X 后期召回并进入最终')
eq(m2.tracks.find(t => t.docId === 'A').status, 'dropped', 'A 首列命中但被淘汰')

/* ---- 场景 3：只出现在第 2 列，未进最终 → appeared ---- */
const resp3 = {
  stages: [
    { name: 'dense', results: [{ doc_id: 'A', rank: 1 }] },
    { name: 'bm25',  results: [{ doc_id: 'A', rank: 1 }, { doc_id: 'Y', rank: 2 }] },
  ],
  final: { doc_ids: ['A'], results: [{ doc_id: 'A', rank: 1 }] },
}
eq(buildModel(resp3).tracks.find(t => t.docId === 'Y').status, 'appeared', 'Y 后期出现但未进最终 → appeared')

/* ---- 场景 4：空数据不崩溃 ---- */
const m4 = buildModel({ stages: [], final: {} })
eq(m4.tracks.length, 0, '空数据无轨迹')
eq(m4.columns.map(c => c.key), ['final'], '空数据仅 final 列')

/* ---- 场景 5：缺失 rank 时用索引兜底 ---- */
const m5 = buildModel({
  stages: [{ name: 'dense', results: [{ doc_id: 'A' }, { doc_id: 'B' }] }],
  final: {},
})
eq(m5.tracks.map(t => t.points[0].rank), [0, 1], '无 rank 时按索引兜底')

/* ---- 场景 6：排序把进入最终的排在前面 ---- */
const m6 = buildModel({
  stages: [{ name: 'dense', results: [
    { doc_id: 'Z', rank: 1 }, { doc_id: 'Y', rank: 2 }, { doc_id: 'X', rank: 3 },
  ]}],
  final: { doc_ids: ['X'], results: [{ doc_id: 'X', rank: 1 }] },
})
eq(m6.tracks[0].docId, 'X', '进入最终的排在最前（尽管初始位次最后）')

console.log(`\n${pass} pass / ${fail} fail`)
process.exit(fail === 0 ? 0 : 1)
