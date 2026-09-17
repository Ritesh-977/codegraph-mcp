import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  expandDir, fetchFileDetail, fetchFindings, fetchGraph, fetchImpact, fetchRepos,
  fetchSubgraph, search,
} from './api'
import type {
  FileDetail, FindingKind, Findings, GraphPayload, Highlight, ImpactPayload, RepoInfo,
} from './types'
import { toElements } from './graph/toCytoscape'
import { GraphCanvas, type LayoutName } from './components/GraphCanvas'
import { TopBar } from './components/TopBar'
import { DetailPanel } from './components/DetailPanel'
import { ImpactPanel } from './components/ImpactPanel'
import { FindingsPanel } from './components/FindingsPanel'

export function App() {
  const [repos, setRepos] = useState<RepoInfo[]>([])
  const [graphId, setGraphId] = useState<string | null>(null)
  const [view, setView] = useState<'overview' | 'full'>('full')
  const [layout, setLayout] = useState<LayoutName>('architecture')
  const [payload, setPayload] = useState<GraphPayload | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<FileDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [impact, setImpact] = useState<ImpactPayload | null>(null)
  const [impactLoading, setImpactLoading] = useState(false)
  const [findings, setFindings] = useState<Findings | null>(null)
  const [findingsLoading, setFindingsLoading] = useState(false)
  const [highlight, setHighlight] = useState<Highlight | null>(null)
  const [focusRequest, setFocusRequest] = useState<{ id: string; nonce: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const elements = useMemo(() => (payload ? toElements(payload) : []), [payload])
  const nodes = useMemo(() => payload?.nodes ?? [], [payload])

  useEffect(() => {
    fetchRepos().then(setRepos).catch((e: Error) => setError(e.message))
  }, [])

  const loadGraph = useCallback(async (id: string, v: 'overview' | 'full') => {
    try {
      setPayload(await fetchGraph(id, v))
      setSelectedId(null)
      setDetail(null)
      setImpact(null)
      setHighlight(null)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  const onRepo = useCallback((id: string) => {
    setGraphId(id)
    setView('full')
    loadGraph(id, 'full')
    setFindings(null)
    setFindingsLoading(true)
    fetchFindings(id)
      .then(setFindings)
      .catch((e: Error) => setError(e.message))
      .finally(() => setFindingsLoading(false))
  }, [loadGraph])

  const onView = useCallback((v: 'overview' | 'full') => {
    setView(v)
    if (graphId) loadGraph(graphId, v)
  }, [graphId, loadGraph])

  const selectedNode = useMemo(
    () => (payload && selectedId ? payload.nodes.find((n) => n.id === selectedId) ?? null : null),
    [payload, selectedId],
  )

  const openFile = useCallback(async (path: string) => {
    if (!graphId) return
    setDetailLoading(true)
    try {
      setDetail(await fetchFileDetail(graphId, path))
      setError(null)
    } catch (e) {
      setDetail(null)
      setError((e as Error).message)
    } finally {
      setDetailLoading(false)
    }
  }, [graphId])

  const onNodeSelect = useCallback(async (id: string | null) => {
    setSelectedId(id)
    setImpact(null)
    if (!id || !graphId || !payload) return
    const node = payload.nodes.find((n) => n.id === id)
    if (!node) return
    if (node.kind === 'file' && node.path) {
      openFile(node.path)
    } else if (node.kind === 'dir_cluster' && node.path) {
      try {
        const res = await expandDir(graphId, node.path)
        setPayload({
          ...payload,
          nodes: payload.nodes.filter((n) => n.id !== id).concat(res.nodes),
          edges: dedupeEdges(payload.edges.concat(res.edges)),
        })
      } catch (e) {
        setError((e as Error).message)
      }
    } else {
      setDetail(null)
    }
  }, [graphId, payload, openFile])

  const onRequestImpact = useCallback(async () => {
    const path = detail?.path ?? selectedNode?.path
    if (!graphId || !path) return
    setImpactLoading(true)
    try {
      setImpact(await fetchImpact({ graph_id: graphId, seed_path: path, max_hops: 2 }))
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setImpactLoading(false)
    }
  }, [graphId, detail, selectedNode])

  const onRequestNeighborhood = useCallback(async () => {
    const path = selectedNode?.path
    if (!graphId || !path) return
    try {
      setPayload(await fetchSubgraph({
        graph_id: graphId, seed_path: path, direction: 'both', depth: 2, include_symbols: true,
      }))
      setSelectedId(`file:${path}`)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [graphId, selectedNode])

  // Focusing a path from a panel: bring it into the graph if the current view
  // does not contain it, then centre on it.
  const focusPath = useCallback((path: string) => {
    const id = `file:${path}`
    if (payload && !payload.nodes.some((n) => n.id === id) && view !== 'full' && graphId) {
      setView('full')
      loadGraph(graphId, 'full').then(() => setFocusRequest({ id, nonce: Date.now() }))
    } else {
      setFocusRequest({ id, nonce: Date.now() })
    }
    setSelectedId(id)
    openFile(path)
  }, [payload, view, graphId, loadGraph, openFile])

  const onSearch = useCallback(async (q: string) => {
    if (!graphId || !q.trim()) return
    try {
      const hits = await search(graphId, q)
      // Function hits carry no path and their id is a Neo4j elementId, not a
      // canvas node id — only a file hit can be focused.
      const hit = hits.find((h) => h.path)
      if (hit) focusPath(hit.path)
      else setError(hits.length ? `Only function matches for "${q}".` : `No match for "${q}".`)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [graphId, focusPath])

  const activeFinding: FindingKind | null = highlight?.kind ?? null

  return (
    <div className="app">
      <TopBar
        repos={repos}
        graphId={graphId}
        view={view}
        layout={layout}
        onRepo={onRepo}
        onView={onView}
        onLayout={setLayout}
        onSearch={onSearch}
      />

      {error && (
        <div className="banner">
          <span className="banner__text">{error}</span>
          <button className="btn btn--ghost" onClick={() => setError(null)}>dismiss</button>
        </div>
      )}

      <div className="app__body">
        {impact || impactLoading ? (
          <ImpactPanel
            impact={impact}
            loading={impactLoading}
            onClose={() => setImpact(null)}
            onFocusPath={focusPath}
          />
        ) : (
          graphId && (
            <FindingsPanel
              findings={findings}
              loading={findingsLoading}
              active={activeFinding}
              onHighlight={setHighlight}
              onFocusPath={focusPath}
            />
          )
        )}

        <div className="app__center">
          <GraphCanvas
            elements={elements}
            nodes={nodes}
            layout={layout}
            selectedNodeId={selectedId}
            highlight={highlight}
            onNodeSelect={onNodeSelect}
            onNodeHover={NOOP}
            focusRequest={focusRequest}
          />

          {!graphId && (
            <div className="placeholder">
              <h2>Pick a repository</h2>
              <p>
                The graph opens as an architecture view: one row per dependency layer,
                entry points on top, and node size by how many files depend on it.
              </p>
            </div>
          )}

          {payload && (
            <div className="hud">
              <span>{payload.stats.file_count} files</span>
              <span className="hud__sep" />
              <span>{payload.stats.edge_count} imports</span>
              {payload.stats.truncated && (
                <>
                  <span className="hud__sep" />
                  <span className="badge badge--hidden">capped — use Directories</span>
                </>
              )}
              <span className="hud__sep" />
              <button className="btn" disabled={!selectedNode?.path} onClick={onRequestNeighborhood}>
                Isolate neighbourhood
              </button>
            </div>
          )}
        </div>

        <DetailPanel
          detail={detail}
          loading={detailLoading}
          onClose={() => { setDetail(null); setSelectedId(null) }}
          onFocusPath={focusPath}
          onImpact={onRequestImpact}
        />
      </div>
    </div>
  )
}

const NOOP = () => {}

function dedupeEdges(edges: GraphPayload['edges']): GraphPayload['edges'] {
  const seen = new Set<string>()
  const out: GraphPayload['edges'] = []
  for (const e of edges) {
    const k = `${e.source}>${e.target}`
    if (!seen.has(k)) {
      seen.add(k)
      out.push(e)
    }
  }
  return out
}
