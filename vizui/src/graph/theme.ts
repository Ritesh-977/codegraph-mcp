import type { GraphNode } from '../types'

export const LANGUAGE_COLORS: Record<string, string> = {
  python: '#4B8BBE',
  javascript: '#F7DF1E',
  typescript: '#3178C6',
  java: '#E76F00',
  kotlin: '#7F52FF',
}

export const KIND_COLORS: Record<string, string> = {
  file: '#3E8FB0',
  dir_cluster: '#7A5CF0',
  symbol: '#C96A4B',
  function: '#4CAF88',
}

export function nodeBaseColor(node: GraphNode): string {
  if (node.kind === 'file' && node.language && LANGUAGE_COLORS[node.language]) {
    return LANGUAGE_COLORS[node.language]
  }
  return KIND_COLORS[node.kind] ?? '#888'
}
