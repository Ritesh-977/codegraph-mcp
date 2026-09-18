export type GraphNodeKind = 'file' | 'dir_cluster' | 'symbol' | 'function'

export interface GraphNode {
  id: string
  kind: GraphNodeKind
  label: string
  path: string | null
  language: string | null
  file_count: number | null
  /** Row in the architecture view: longest path from an entry point. Null for
   *  external symbols, which belong to no layer of this codebase. */
  layer: number | null
  fan_in: number | null
  fan_out: number | null
  in_cycle: boolean
  /** Commits touching this file in the clone's history; null if unavailable. */
  commits: number | null
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

export interface HubEntry {
  path: string
  dependents: number
  dependencies: number
}

export interface CycleEntry {
  paths: string[]
}

export interface CouplingEntry {
  a: string
  b: string
  shared_commits: number
  strength: number
  /** False = the two files change together with nothing in the code saying so. */
  has_import_edge: boolean
}

export interface RiskEntry {
  path: string
  commits: number
  dependents: number
  score: number
}

export interface Findings {
  graph_id: string
  file_count: number
  edge_count: number
  max_layer: number
  hubs: HubEntry[]
  entry_points: string[]
  orphans: string[]
  cycles: CycleEntry[]
  risk: RiskEntry[]
  coupling: CouplingEntry[]
  coupling_available: boolean
  coupling_hint: string | null
}

export type FindingKind = 'risk' | 'hubs' | 'entries' | 'orphans' | 'cycles' | 'coupling'

export interface Highlight {
  kind: FindingKind
  /** Cytoscape node ids to flag. */
  ids: string[]
  /** Extra non-import edges to draw (used by coupling). */
  pairs?: [string, string][]
  critical?: boolean
}
