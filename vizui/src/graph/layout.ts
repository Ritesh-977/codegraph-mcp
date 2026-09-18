import type { GraphEdge, GraphNode } from '../types'

export const ROW_GAP = 190
export const COL_GAP = 130
const MIN_R = 9
const MAX_R = 32
const SWEEPS = 6
const TRANSPOSE_PASSES = 4
const TRANSPOSE_LIMIT = 1200

/**
 * Node radius from dependents. Square-root so a file with 21 dependents reads
 * as clearly bigger than one with 3 without swamping the canvas — area, not
 * radius, is what the eye compares.
 */
export function nodeRadius(fanIn: number | null): number {
  const n = Math.max(0, fanIn ?? 0)
  return Math.min(MAX_R, MIN_R + Math.sqrt(n) * 4.5)
}

export type RowOrder = 'barycenter' | 'path'

/** Nodes grouped into their rows, external symbols parked below the deepest layer. */
function buildRows(nodes: GraphNode[]): Map<number, GraphNode[]> {
  const rows = new Map<number, GraphNode[]>()
  let deepest = 0
  for (const n of nodes) {
    if (n.layer === null) continue
    deepest = Math.max(deepest, n.layer)
    const row = rows.get(n.layer)
    if (row) row.push(n)
    else rows.set(n.layer, [n])
  }
  const symbols = nodes.filter((n) => n.layer === null)
  if (symbols.length) rows.set(deepest + 1, symbols)
  // Sort by path first: a stable, meaningful starting order (sibling
  // directories adjacent) that the sweep then refines, and the final answer
  // where a row has no edges to constrain it.
  for (const row of rows.values()) {
    row.sort((a, b) => (a.path ?? a.label).localeCompare(b.path ?? b.label))
  }
  return rows
}

/**
 * Order each row to reduce edge crossings (the barycenter heuristic from
 * Sugiyama layered drawing).
 *
 * Path order alone is arbitrary with respect to the edges, so a graph with a
 * few hundred imports over a handful of rows crosses about as much as it
 * possibly can. Each pass moves every node next to the average position of the
 * nodes it connects to in the rows above (downward pass) then below (upward
 * pass); alternating a few times settles it. Positions are normalised to [0,1]
 * within a row so rows of very different widths still compare fairly, which
 * also lets edges that span more than one layer pull sensibly without needing
 * dummy nodes.
 */
function sweep(rows: Map<number, GraphNode[]>, edges: GraphEdge[]): void {
  const layers = [...rows.keys()].sort((a, b) => a - b)
  if (layers.length < 2) return

  const layerOf = new Map<string, number>()
  for (const [layer, row] of rows) for (const n of row) layerOf.set(n.id, layer)

  const preds = new Map<string, string[]>()
  const succs = new Map<string, string[]>()
  for (const e of edges) {
    if (!layerOf.has(e.source) || !layerOf.has(e.target)) continue
    ;(succs.get(e.source) ?? succs.set(e.source, []).get(e.source)!).push(e.target)
    ;(preds.get(e.target) ?? preds.set(e.target, []).get(e.target)!).push(e.source)
  }

  const norm = new Map<string, number>()
  const renormalise = (): void => {
    for (const row of rows.values()) {
      const last = Math.max(1, row.length - 1)
      row.forEach((n, i) => norm.set(n.id, i / last))
    }
  }
  renormalise()

  const reorder = (layer: number, neighbours: Map<string, string[]>): void => {
    const row = rows.get(layer)
    if (!row || row.length < 2) return
    const keyed = row.map((n, i) => {
      const ns = neighbours.get(n.id) ?? []
      const vals = ns.map((id) => norm.get(id)).filter((v): v is number => v !== undefined)
      // A node with no neighbours in that direction keeps its current slot
      // rather than being flung to one end.
      const bary = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : norm.get(n.id) ?? 0
      return { n, bary, i }
    })
    keyed.sort((a, b) => a.bary - b.bary || a.i - b.i)
    rows.set(layer, keyed.map((k) => k.n))
  }

  for (let pass = 0; pass < SWEEPS; pass++) {
    const down = pass % 2 === 0
    const order = down ? layers : [...layers].reverse()
    for (const layer of order) reorder(layer, down ? preds : succs)
    renormalise()
  }

  // Transpose refinement: barycenter gets the rows roughly right, then greedy
  // adjacent swaps clean up what averaging cannot see. Skipped on very large
  // graphs, where it is quadratic in row width for a shrinking return.
  if (nodeCount(rows) <= TRANSPOSE_LIMIT) transpose(rows, layers, edges, layerOf)
}

/** Crossings contributed by the edges running between two specific rows. */
function pairCrossings(
  upper: Map<string, number>,
  lower: Map<string, number>,
  spans: GraphEdge[],
): number {
  let c = 0
  for (let i = 0; i < spans.length; i++) {
    for (let j = i + 1; j < spans.length; j++) {
      const a = spans[i]
      const b = spans[j]
      const ds = upper.get(a.source)! - upper.get(b.source)!
      const dt = lower.get(a.target)! - lower.get(b.target)!
      if (ds * dt < 0) c++
    }
  }
  return c
}

function nodeCount(rows: Map<number, GraphNode[]>): number {
  let n = 0
  for (const row of rows.values()) n += row.length
  return n
}

function transpose(
  rows: Map<number, GraphNode[]>,
  layers: number[],
  edges: GraphEdge[],
  layerOf: Map<string, number>,
): void {
  // Index edges by the (source layer, target layer) pair they span.
  const byPair = new Map<string, GraphEdge[]>()
  for (const e of edges) {
    const a = layerOf.get(e.source)
    const b = layerOf.get(e.target)
    if (a === undefined || b === undefined) continue
    const key = `${a}>${b}`
    const list = byPair.get(key)
    if (list) list.push(e)
    else byPair.set(key, [e])
  }

  const indexOf = (layer: number): Map<string, number> => {
    const m = new Map<string, number>()
    rows.get(layer)?.forEach((n, i) => m.set(n.id, i))
    return m
  }

  // Every layer pair this layer participates in, so a swap is scored against
  // all of its edges rather than just the row below.
  const touching = (layer: number): [number, number, GraphEdge[]][] => {
    const out: [number, number, GraphEdge[]][] = []
    for (const [key, list] of byPair) {
      const [a, b] = key.split('>').map(Number)
      if (a === layer || b === layer) out.push([a, b, list])
    }
    return out
  }

  const score = (layer: number): number => {
    let total = 0
    for (const [a, b, list] of touching(layer)) {
      total += pairCrossings(indexOf(a), indexOf(b), list)
    }
    return total
  }

  for (let pass = 0; pass < TRANSPOSE_PASSES; pass++) {
    let improved = false
    for (const layer of layers) {
      const row = rows.get(layer)
      if (!row || row.length < 2) continue
      for (let i = 0; i < row.length - 1; i++) {
        const before = score(layer)
        ;[row[i], row[i + 1]] = [row[i + 1], row[i]]
        if (score(layer) < before) improved = true
        else [row[i], row[i + 1]] = [row[i + 1], row[i]]
      }
    }
    if (!improved) break
  }
}

/**
 * Lay the graph out as an architecture diagram: one row per dependency layer,
 * entry points on top, leaves at the bottom. Position is the whole point here —
 * a force-directed blob puts nodes wherever physics lands them, so nothing is
 * learnable. Here the row is the dependency depth and the order within it is
 * chosen to keep the edges untangled.
 */
export function architecturePositions(
  nodes: GraphNode[],
  edges: GraphEdge[],
  order: RowOrder = 'barycenter',
): Record<string, { x: number; y: number }> {
  if (nodes.length === 0) return {}
  const rows = buildRows(nodes)
  if (order === 'barycenter') sweep(rows, edges)

  const widest = Math.max(...[...rows.values()].map((r) => r.length))
  const canvasWidth = widest * COL_GAP
  const pos: Record<string, { x: number; y: number }> = {}
  for (const [layer, row] of rows) {
    const span = (row.length - 1) * COL_GAP
    const startX = (canvasWidth - span) / 2
    row.forEach((n, i) => {
      pos[n.id] = { x: startX + i * COL_GAP, y: layer * ROW_GAP }
    })
  }
  return pos
}

/**
 * Count edge crossings for a given row ordering — the objective the sweep
 * minimises, exported so the improvement is measurable rather than asserted.
 * Two edges between the same pair of rows cross when their endpoints are in
 * opposite horizontal order.
 */
export function countCrossings(
  nodes: GraphNode[],
  edges: GraphEdge[],
  opts: { order?: RowOrder } = {},
): number {
  const pos = architecturePositions(nodes, edges, opts.order ?? 'barycenter')
  const layerOf = new Map(nodes.map((n) => [n.id, n.layer]))
  const spans = edges.filter((e) => pos[e.source] && pos[e.target])
  let crossings = 0
  for (let i = 0; i < spans.length; i++) {
    for (let j = i + 1; j < spans.length; j++) {
      const a = spans[i]
      const b = spans[j]
      // Only comparable when both edges run between the same two rows.
      if (layerOf.get(a.source) !== layerOf.get(b.source)) continue
      if (layerOf.get(a.target) !== layerOf.get(b.target)) continue
      const ds = pos[a.source].x - pos[b.source].x
      const dt = pos[a.target].x - pos[b.target].x
      if (ds * dt < 0) crossings++
    }
  }
  return crossings
}
