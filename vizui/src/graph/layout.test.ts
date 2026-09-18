import { describe, expect, it } from 'vitest'
import type { GraphEdge, GraphNode } from '../types'
import { architecturePositions, countCrossings, nodeRadius } from './layout'

const n = (id: string, layer: number | null, path: string | null = id): GraphNode => ({
  id, kind: layer === null ? 'symbol' : 'file', label: id, path, language: null,
  file_count: null, layer, fan_in: 0, fan_out: 0, in_cycle: false, commits: null,
})
const e = (source: string, target: string): GraphEdge => ({
  source, target, type: 'IMPORTS', weight: 1,
})

describe('architecturePositions', () => {
  it('puts each layer on its own descending row', () => {
    const pos = architecturePositions([n('a', 0), n('b', 1), n('c', 2)], [e('a', 'b'), e('b', 'c')])
    expect(pos['a'].y).toBeLessThan(pos['b'].y)
    expect(pos['b'].y).toBeLessThan(pos['c'].y)
  })

  it('shares one row across a layer', () => {
    const pos = architecturePositions([n('z', 0, 'server/z.js'), n('a', 0, 'client/a.js')], [])
    expect(pos['a'].y).toBe(pos['z'].y)
  })

  it('falls back to path order when no edges constrain a row', () => {
    const pos = architecturePositions([n('z', 0, 'server/z.js'), n('a', 0, 'client/a.js')], [])
    expect(pos['a'].x).toBeLessThan(pos['z'].x)
  })

  it('parks external symbols below the deepest layer', () => {
    const pos = architecturePositions([n('a', 0), n('deep', 3), n('os', null, null)], [])
    expect(pos['os'].y).toBeGreaterThan(pos['deep'].y)
  })

  it('handles an empty graph without dividing by zero', () => {
    expect(architecturePositions([], [])).toEqual({})
  })

  it('reorders rows to remove crossings that path order creates', () => {
    // a->z, b->y, c->x. Alphabetical order on both rows crosses every pair;
    // ordering the lower row z,y,x removes all three crossings.
    const nodes = [n('a', 0), n('b', 0), n('c', 0), n('x', 1), n('y', 1), n('z', 1)]
    const edges = [e('a', 'z'), e('b', 'y'), e('c', 'x')]
    const alphabetical = countCrossings(nodes, edges, { order: 'path' })
    const swept = countCrossings(nodes, edges, { order: 'barycenter' })
    expect(alphabetical).toBe(3)
    expect(swept).toBe(0)
  })

  it('never increases crossings on a denser graph', () => {
    const nodes = [
      ...['a', 'b', 'c', 'd'].map((i) => n(i, 0)),
      ...['p', 'q', 'r', 's'].map((i) => n(i, 1)),
    ]
    const edges = [
      e('a', 's'), e('b', 'r'), e('c', 'q'), e('d', 'p'),
      e('a', 'r'), e('d', 'q'),
    ]
    expect(countCrossings(nodes, edges, { order: 'barycenter' }))
      .toBeLessThanOrEqual(countCrossings(nodes, edges, { order: 'path' }))
  })
})

describe('nodeRadius', () => {
  it('grows with dependents and stays bounded', () => {
    expect(nodeRadius(0)).toBeLessThan(nodeRadius(5))
    expect(nodeRadius(5)).toBeLessThan(nodeRadius(50))
    expect(nodeRadius(10_000)).toBeLessThanOrEqual(64)
  })
})

describe('sweep quality on a graph big enough to tangle', () => {
  // 6 rows x 10 nodes, wired so that path order is close to worst-case: each
  // node connects to reversed positions in the row below.
  const nodes: GraphNode[] = []
  const edges: GraphEdge[] = []
  for (let layer = 0; layer < 6; layer++) {
    for (let i = 0; i < 10; i++) nodes.push(n(`L${layer}_${i}`, layer))
  }
  for (let layer = 0; layer < 5; layer++) {
    for (let i = 0; i < 10; i++) {
      edges.push(e(`L${layer}_${i}`, `L${layer + 1}_${9 - i}`))
      if (i % 3 === 0) edges.push(e(`L${layer}_${i}`, `L${layer + 1}_${(i + 4) % 10}`))
    }
  }

  it('cuts crossings substantially versus path order', () => {
    const before = countCrossings(nodes, edges, { order: 'path' })
    const after = countCrossings(nodes, edges, { order: 'barycenter' })
    expect(before).toBeGreaterThan(0)
    expect(after).toBeLessThan(before * 0.5)
  })

  it('is deterministic — same input, same layout', () => {
    const a = architecturePositions(nodes, edges)
    const b = architecturePositions(nodes, edges)
    expect(a).toEqual(b)
  })
})
