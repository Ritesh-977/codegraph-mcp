import type { ElementDefinition } from 'cytoscape'
import type { GraphEdge, GraphNode, GraphPayload } from '../types'
import { nodeRadius } from './layout'

// Class names are the stylesheet's contract — see graph/style.ts.
export function nodeClassName(n: GraphNode): string {
  const parts = [`node-${n.kind}`]
  if (n.language) parts.push(`lang-${n.language}`)
  // An entry point is a place to start reading; mark it structurally (shape)
  // rather than by colour, which is reserved.
  if (n.kind === 'file' && n.fan_in === 0 && (n.fan_out ?? 0) > 0) parts.push('is-entry')
  if (n.in_cycle) parts.push('in-cycle')
  return parts.join(' ')
}

export function edgeClassName(e: GraphEdge): string {
  return `edge-${e.type}`
}

export function toElements(payload: GraphPayload): ElementDefinition[] {
  const nodeEls: ElementDefinition[] = payload.nodes.map((n) => ({
    data: {
      id: n.id,
      kind: n.kind,
      label: n.label,
      path: n.path ?? undefined,
      language: n.language ?? undefined,
      fileCount: n.file_count ?? undefined,
      layer: n.layer ?? undefined,
      fanIn: n.fan_in ?? 0,
      fanOut: n.fan_out ?? 0,
      // Radius lives in data so the stylesheet maps it directly; a dir cluster
      // is sized by how many files it holds, a file by how many depend on it.
      size: n.kind === 'dir_cluster'
        ? Math.min(70, 30 + Math.sqrt(n.file_count ?? 1) * 5)
        : nodeRadius(n.fan_in) * 2,
    },
    classes: nodeClassName(n),
  }))
  const edgeEls: ElementDefinition[] = payload.edges.map((e, i) => ({
    data: {
      id: `${e.source}>${e.target}:${i}`,
      source: e.source,
      target: e.target,
      edgeType: e.type,
      weight: e.weight,
    },
    classes: edgeClassName(e),
  }))
  return [...nodeEls, ...edgeEls]
}
