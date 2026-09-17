export type GraphNodeKind = 'file' | 'dir_cluster' | 'symbol' | 'function'

export interface GraphNode {
  id: string
  kind: GraphNodeKind
  label: string
  path: string | null
  language: string | null
  file_count: number | null
}

export interface GraphEdge {
  source: string
  target: string
  type: 'IMPORTS' | 'CALLS' | 'DEFINES'
  weight: number
}

export interface GraphStats {
  file_count: number
  edge_count: number
  truncated: boolean
  view: string
}

export interface GraphPayload {
  graph_id: string
  view: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats: GraphStats
}

export interface SubgraphRequest {
  graph_id: string
  seed_path: string
  direction: 'imports' | 'imported_by' | 'both'
  depth: number
  include_symbols: boolean
}

export interface ImpactRequest {
  graph_id: string
  seed_path: string
  max_hops: number
}

export interface ImpactRing {
  hop: number
  paths: string[]
}

export interface ImpactPayload {
  graph_id: string
  seed_path: string
  rings: ImpactRing[]
  callers: string[]
  calls: string[]
  truncated: boolean
}

export interface ExpandResult {
  graph_id: string
  dir_prefix: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface FunctionInfo {
  name: string
  qualified_name: string
  kind: string
  start_line: number
  end_line: number
}

export interface FileDetail {
  graph_id: string
  path: string
  language: string | null
  last_author: string | null
  last_commit_at: string | null
  last_commit_sha: string | null
  content: string
  start_line: number
  end_line: number
  truncated: boolean
  functions: FunctionInfo[]
  imported_by: string[]
  imports: string[]
  external_symbols: string[]
}

export interface RepoInfo {
  graph_id: string
  name: string
  url: string
  default_branch: string | null
  ingested_at: string | null
  ingest_status: string
}

export interface SearchHit {
  id: string
  name: string
  kind: string
  path: string
  qualified_name: string
  score: number
}
