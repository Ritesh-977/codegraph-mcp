import { describe, expect, it } from 'vitest'
import type { GraphNode, GraphPayload } from '../types'
import { toElements } from './toCytoscape'

const payload: GraphPayload = {
  graph_id: 'o/n',
  view: 'full',
  nodes: [
    { id: 'file:a.py', kind: 'file', label: 'a.py', path: 'a.py', language: 'python', file_count: null, layer: 0, fan_in: 4, fan_out: 1, in_cycle: false },
    { id: 'sym:os', kind: 'symbol', label: 'os', path: null, language: null, file_count: null, layer: null, fan_in: null, fan_out: null, in_cycle: false },
    { id: 'dir:src', kind: 'dir_cluster', label: 'src', path: 'src', language: null, file_count: 3, layer: 1, fan_in: 0, fan_out: 0, in_cycle: false },
  ],
  edges: [{ source: 'file:a.py', target: 'sym:os', type: 'IMPORTS', weight: 1 }],
  stats: { file_count: 1, edge_count: 1, truncated: false, view: 'full' },
}

describe('toElements', () => {
  it('maps nodes to cytoscape data with classes', () => {
    const els = toElements(payload)
    // Filter on the absence of `source`: edge ids also start with `file:`.
    const nodeEls = els.filter(
      (e) => !('source' in (e.data ?? {})) && (e.data as { id?: string }).id?.startsWith('file:'),
    )
    expect(nodeEls).toHaveLength(1)
    const n = nodeEls[0]
    expect((n.data as { id: string }).id).toBe('file:a.py')
    expect((n.data as { path?: string }).path).toBe('a.py')
    expect((n.classes as string).split(' ')).toContain('node-file')
    expect((n.classes as string).split(' ')).toContain('lang-python')
  })

  it('maps edges with source/target and type class', () => {
    const els = toElements(payload)
    const edge = els.find((e) => 'source' in (e.data ?? {}))!
    expect(edge.data.source).toBe('file:a.py')
    expect(edge.data.target).toBe('sym:os')
    expect((edge.classes as string).split(' ')).toContain('edge-IMPORTS')
  })

  it('carries size and metrics into node data for the stylesheet', () => {
    // Files and dir clusters are sized on separate scales on purpose (a
    // container vs a node), so importance is only comparable file-to-file.
    const withFanIn = (id: string, fan_in: number): GraphNode => ({
      id, kind: 'file', label: id, path: id, language: null,
      file_count: null, layer: 0, fan_in, fan_out: 0, in_cycle: false,
    })
    const els = toElements({
      ...payload,
      nodes: [withFanIn('file:big', 20), withFanIn('file:small', 1)],
      edges: [],
    })
    const size = (id: string) =>
      (els.find((e) => (e.data as { id?: string }).id === id)!.data as { size: number }).size
    expect(size('file:big')).toBeGreaterThan(size('file:small'))

    const a = toElements(payload).find((e) => (e.data as { id?: string }).id === 'file:a.py')!
    expect((a.data as { fanIn: number }).fanIn).toBe(4)
  })

  it('gives every element a unique id', () => {
    const ids = toElements(payload).map((e) => (e.data as { id?: string }).id).filter(Boolean)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('emits classes the stylesheet actually selects on', () => {
    // Regression guard: the stylesheet keys off `node-<kind>`, so a rename
    // here silently un-styles symbols and directory clusters.
    const els = toElements(payload)
    const byId = new Map(els.map((e) => [(e.data as { id?: string }).id, e]))
    expect((byId.get('sym:os')!.classes as string).split(' ')).toContain('node-symbol')
    expect((byId.get('dir:src')!.classes as string).split(' ')).toContain('node-dir_cluster')
  })
})
