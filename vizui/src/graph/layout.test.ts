import { describe, expect, it } from 'vitest'
import type { GraphNode } from '../types'
import { architecturePositions, nodeRadius } from './layout'

const n = (id: string, layer: number | null, path: string | null = id): GraphNode => ({
  id, kind: layer === null ? 'symbol' : 'file', label: id, path, language: null,
  file_count: null, layer, fan_in: 0, fan_out: 0, in_cycle: false,
})

describe('architecturePositions', () => {
  it('puts each layer on its own descending row', () => {
    const pos = architecturePositions([n('a', 0), n('b', 1), n('c', 2)])
    expect(pos['a'].y).toBeLessThan(pos['b'].y)
    expect(pos['b'].y).toBeLessThan(pos['c'].y)
  })

  it('shares one row across a layer and orders it by path', () => {
    const pos = architecturePositions([n('z', 0, 'server/z.js'), n('a', 0, 'client/a.js')])
    expect(pos['a'].y).toBe(pos['z'].y)
    // client/ sorts before server/, so directories stay grouped left-to-right
    expect(pos['a'].x).toBeLessThan(pos['z'].x)
  })

  it('parks external symbols below the deepest layer', () => {
    const pos = architecturePositions([n('a', 0), n('deep', 3), n('os', null, null)])
    expect(pos['os'].y).toBeGreaterThan(pos['deep'].y)
  })

  it('centres every row on the same axis', () => {
    const pos = architecturePositions([n('a', 0), n('x', 1), n('y', 1)])
    const rowCentre = (pos['x'].x + pos['y'].x) / 2
    expect(Math.abs(pos['a'].x - rowCentre)).toBeLessThan(1)
  })

  it('handles an empty graph without dividing by zero', () => {
    expect(architecturePositions([])).toEqual({})
  })
})

describe('nodeRadius', () => {
  it('grows with dependents and stays bounded', () => {
    expect(nodeRadius(0)).toBeLessThan(nodeRadius(5))
    expect(nodeRadius(5)).toBeLessThan(nodeRadius(50))
    expect(nodeRadius(10_000)).toBeLessThanOrEqual(64)
  })
})
