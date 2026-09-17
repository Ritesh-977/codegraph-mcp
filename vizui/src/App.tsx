import { useCallback, useEffect, useRef, useState } from 'react'
import type { ElementDefinition } from 'cytoscape'
import {
  expandDir,
  fetchFileDetail,
  fetchGraph,
  fetchImpact,
  fetchRepos,
  fetchSubgraph,
  search,
} from './api'
import type { FileDetail, GraphPayload, ImpactPayload, RepoInfo } from './types'
import { toElements } from './graph/toCytoscape'
import { GraphCanvas } from './components/GraphCanvas'
import { TopBar } from './components/TopBar'
import { DetailPanel } from './components/DetailPanel'
import { ImpactPanel } from './components/ImpactPanel'

const BTN: React.CSSProperties = {
  background: '#1a2029',
  color: '#e8e8e8',
  border: '1px solid #39424f',
  borderRadius: 4,
  padding: '2px 8px',
  cursor: 'pointer',
  marginLeft: 8,
}

export function App() {
  const [repos, setRepos] = useState<RepoInfo[]>([])
  const [graphId, setGraphId] = useState<string | null>(null)
  const [view, setView] = useState<'overview' | 'full'>('overview')
  const [layout, setLayout] = useState<'fcose' | 'concentric' | 'breadthfirst'>('fcose')
  const [elements, setElements] = useState<ElementDefinition[]>([])
  const [payload, setPayload] = useState<GraphPayload | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<FileDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [impact, setImpact] = useState<ImpactPayload | null>(null)
  const [impactLoading, setImpactLoading] = useState(false)
  const [focusRequest, setFocusRequest] = useState<{ id: string; nonce: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const expandedClusters = useRef<Set<string>>(new Set())

  useEffect(() => {
    fetchRepos().then(setRepos).catch((e: Error) => setError(e.message))
  }, [])

  const show = useCallback((p: GraphPayload) => {
    setPayload(p)
    setElements(toElements(p))
  }, [])

  const loadGraph = useCallback(
    async (id: string, v: 'overview' | 'full') => {
      try {
        const p = await fetchGraph(id, v)
        expandedClusters.current = new Set()
        show(p)
        setSelectedId(null)
        setDetail(null)
        setImpact(null)
        setError(null)
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [show],
  )

  const onRepo = useCallback(
    (id: string) => {
      setGraphId(id)
      setView('overview')
      loadGraph(id, 'overview')
    },
    [loadGraph],
  )

  const onView = useCallback(
    (v: 'overview' | 'full') => {
      setView(v)
      if (graphId) loadGraph(graphId, v)
    },
    [graphId, loadGraph],
  )

  const selectedNode = payload && selectedId
    ? payload.nodes.find((n) => n.id === selectedId) ?? null
    : null

  const onNodeSelect = useCallback(
    async (id: string | null) => {
      setSelectedId(id)
      setImpact(null)
      if (!id || !graphId || !payload) return
      const node = payload.nodes.find((n) => n.id === id)
      if (!node) return
      if (node.kind === 'file' && node.path) {
        setDetailLoading(true)
        try {
          setDetail(await fetchFileDetail(graphId, node.path))
          setError(null)
        } catch (e) {
          setDetail(null)
          setError((e as Error).message)
        } finally {
          setDetailLoading(false)
        }
      } else if (node.kind === 'dir_cluster' && node.path) {
        // Expand one level in place: the cluster is replaced by its children.
        try {
          const res = await expandDir(graphId, node.path)
          const next: GraphPayload = {
            ...payload,
            nodes: payload.nodes.filter((n) => n.id !== id).concat(res.nodes),
            edges: dedupeEdges(payload.edges.concat(res.edges)),
          }
          expandedClusters.current.add(node.id)
          show(next)
        } catch (e) {
          setError((e as Error).message)
        }
      } else {
        setDetail(null)
      }
    },
    [graphId, payload, show],
  )

  const onNodeHover = useCallback(() => {}, [])

  const onRequestImpact = useCallback(async () => {
    if (!graphId || !selectedNode?.path) return
    setImpactLoading(true)
    try {
      setImpact(await fetchImpact({ graph_id: graphId, seed_path: selectedNode.path, max_hops: 2 }))
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setImpactLoading(false)
    }
  }, [graphId, selectedNode])

  const onRequestNeighborhood = useCallback(async () => {
    if (!graphId || !selectedNode?.path) return
    try {
      const p = await fetchSubgraph({
        graph_id: graphId,
        seed_path: selectedNode.path,
        direction: 'both',
        depth: 2,
        include_symbols: true,
      })
      show(p)
      setSelectedId(`file:${selectedNode.path}`)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [graphId, selectedNode, show])

  const onSearch = useCallback(
    async (q: string) => {
      if (!graphId) return
      try {
        const hits = await search(graphId, q)
        // Function hits carry no path, and their `id` is a Neo4j elementId,
        // not a canvas node id — only a file hit can be focused.
        const hit = hits.find((h) => h.path)
        if (hit) {
          const id = `file:${hit.path}`
          setFocusRequest({ id, nonce: Date.now() })
          setSelectedId(id)
        } else {
          setError(hits.length ? `No file matches "${q}" (function hits only).` : `No match for "${q}".`)
        }
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [graphId],
  )

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
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
        <div style={{ padding: '6px 14px', background: '#3a1d1d', color: '#ffbcbc', fontSize: 12 }}>
          {error}
          <button onClick={() => setError(null)} style={BTN}>dismiss</button>
        </div>
      )}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {(impact || impactLoading) && (
          <ImpactPanel impact={impact} loading={impactLoading} onClose={() => setImpact(null)} />
        )}
        <div style={{ position: 'relative', flex: 1, display: 'flex', flexDirection: 'column' }}>
          <GraphCanvas
            elements={elements}
            layout={layout}
            selectedNodeId={selectedId}
            onNodeSelect={onNodeSelect}
            onNodeHover={onNodeHover}
            focusRequest={focusRequest}
          />
          {payload && (
            <div style={{ position: 'absolute', left: 12, bottom: 10, fontSize: 12, color: '#9aa4b1', background: 'rgba(16,20,24,0.8)', padding: '4px 8px', borderRadius: 4, zIndex: 11 }}>
              {payload.stats.file_count} files · {payload.stats.edge_count} edges
              {payload.stats.truncated ? ' (truncated — use Overview)' : ''}
              <button onClick={onRequestImpact} disabled={!selectedNode?.path} style={BTN}>
                Impact
              </button>
              <button onClick={onRequestNeighborhood} disabled={!selectedNode?.path} style={BTN}>
                Neighborhood
              </button>
            </div>
          )}
        </div>
        <DetailPanel
          detail={detail}
          loading={detailLoading}
          onClose={() => {
            setDetail(null)
            setSelectedId(null)
          }}
        />
      </div>
    </div>
  )
}

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
