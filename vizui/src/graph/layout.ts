import type { GraphNode } from '../types'

export const ROW_GAP = 190
export const COL_GAP = 130
const MIN_R = 9
const MAX_R = 32

/**
 * Node radius from dependents. Square-root so a file with 21 dependents reads
 * as clearly bigger than one with 3 without swamping the canvas — area, not
 * radius, is what the eye compares.
 */
export function nodeRadius(fanIn: number | null): number {
  const n = Math.max(0, fanIn ?? 0)
  return Math.min(MAX_R, MIN_R + Math.sqrt(n) * 4.5)
}

/**
 * Lay the graph out as an architecture diagram: one row per dependency layer,
 * entry points on top, leaves at the bottom. Position is the whole point here —
 * a force-directed blob puts nodes wherever physics lands them, so nothing is
 * learnable and any edge direction is as likely as any other. Here an edge that
 * points *upward* is a layering violation you can spot at a glance.
 */
export function architecturePositions(nodes: GraphNode[]): Record<string, { x: number; y: number }> {
  if (nodes.length === 0) return {}

  const rows = new Map<number, GraphNode[]>()
  let deepest = 0
  for (const n of nodes) {
    if (n.layer === null) continue
    deepest = Math.max(deepest, n.layer)
    const row = rows.get(n.layer)
    if (row) row.push(n)
    else rows.set(n.layer, [n])
  }
  // External symbols belong to no layer of this codebase; park them one row
  // below the deepest real layer rather than inventing a rank for them.
  const symbolRow = deepest + 1
  const symbols = nodes.filter((n) => n.layer === null)
  if (symbols.length) rows.set(symbolRow, symbols)

  const widest = Math.max(...[...rows.values()].map((r) => r.length))
  const canvasWidth = widest * COL_GAP
  const pos: Record<string, { x: number; y: number }> = {}

  for (const [layer, row] of rows) {
    // Sort by path so sibling directories stay adjacent: the row reads as
    // "client/… then server/…" rather than as a random permutation.
    const ordered = [...row].sort((a, b) => (a.path ?? a.label).localeCompare(b.path ?? b.label))
    const span = (ordered.length - 1) * COL_GAP
    const startX = (canvasWidth - span) / 2
    ordered.forEach((n, i) => {
      pos[n.id] = { x: startX + i * COL_GAP, y: layer * ROW_GAP }
    })
  }
  return pos
}
