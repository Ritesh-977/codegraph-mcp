import type { ElementDefinition } from 'cytoscape'
import type { GraphEdge, GraphNode, GraphPayload } from '../types'
import { nodeBaseColor } from './theme'

// Class names are the stylesheet's contract — see graph/style.ts.
export function nodeClassName(n: GraphNode): string {
  const parts = [`node-${n.kind}`]
  if (n.language) parts.push(`lang-${n.language}`)
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
      color: nodeBaseColor(n),
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
