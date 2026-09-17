import type {
  ExpandResult,
  FileDetail,
  Findings,
  GraphPayload,
  ImpactPayload,
  ImpactRequest,
  RepoInfo,
  SearchHit,
  SubgraphRequest,
} from './types'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    let hint = ''
    try {
      const body = await res.json()
      detail = body.detail ?? detail
      hint = body.hint ?? ''
    } catch {
      /* non-JSON error body */
    }
    throw new Error(hint ? `${detail} — ${hint}` : detail)
  }
  return res.json() as Promise<T>
}

export async function fetchRepos(): Promise<RepoInfo[]> {
  return json(await fetch('/api/repos'))
}

// graph_id carries slashes (`github.com/owner/name`), so it is always a query
// param — never a path segment.
export async function fetchGraph(
  graphId: string,
  view: 'overview' | 'full',
  depth = 1,
): Promise<GraphPayload> {
  const qs = new URLSearchParams({ graph_id: graphId, view, depth: String(depth) })
  return json(await fetch(`/api/graph?${qs}`))
}

export async function fetchSubgraph(req: SubgraphRequest): Promise<GraphPayload> {
  return json(
    await fetch('/api/subgraph', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    }),
  )
}

export async function fetchImpact(req: ImpactRequest): Promise<ImpactPayload> {
  return json(
    await fetch('/api/impact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    }),
  )
}

export async function expandDir(graphId: string, dir: string): Promise<ExpandResult> {
  const qs = new URLSearchParams({ graph_id: graphId, dir })
  return json(await fetch(`/api/expand?${qs}`))
}

export async function search(graphId: string, q: string): Promise<SearchHit[]> {
  const qs = new URLSearchParams({ graph_id: graphId, q, kind: 'any', limit: '20' })
  return json(await fetch(`/api/search?${qs}`))
}

export async function fetchFileDetail(graphId: string, path: string): Promise<FileDetail> {
  const qs = new URLSearchParams({ graph_id: graphId, path })
  return json(await fetch(`/api/file?${qs}`))
}

export async function fetchFindings(graphId: string): Promise<Findings> {
  const qs = new URLSearchParams({ graph_id: graphId })
  return json(await fetch(`/api/findings?${qs}`))
}
