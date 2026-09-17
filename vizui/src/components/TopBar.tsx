import type { RepoInfo } from '../types'

export interface TopBarProps {
  repos: RepoInfo[]
  graphId: string | null
  view: 'overview' | 'full'
  layout: 'fcose' | 'concentric' | 'breadthfirst'
  onRepo: (id: string) => void
  onView: (view: 'overview' | 'full') => void
  onLayout: (l: 'fcose' | 'concentric' | 'breadthfirst') => void
  onSearch: (q: string) => void
}

const LAYOUTS: TopBarProps['layout'][] = ['fcose', 'concentric', 'breadthfirst']
const CONTROL: React.CSSProperties = {
  background: '#1a2029',
  color: '#e8e8e8',
  border: '1px solid #39424f',
  borderRadius: 4,
  padding: 4,
}

export function TopBar(props: TopBarProps) {
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '8px 14px', borderBottom: '1px solid #2b3441' }}>
      <strong>codegraph-viz</strong>
      <select value={props.graphId ?? ''} onChange={(e) => props.onRepo(e.target.value)} style={CONTROL}>
        <option value="" disabled>Select repository…</option>
        {props.repos.map((r) => (
          <option key={r.graph_id} value={r.graph_id}>{r.graph_id}</option>
        ))}
      </select>
      <label style={{ fontSize: 12 }}>
        View{' '}
        <select value={props.view} onChange={(e) => props.onView(e.target.value as 'overview' | 'full')} style={CONTROL}>
          <option value="overview">Overview (clusters)</option>
          <option value="full">Full</option>
        </select>
      </label>
      <label style={{ fontSize: 12 }}>
        Layout{' '}
        <select value={props.layout} onChange={(e) => props.onLayout(e.target.value as TopBarProps['layout'])} style={CONTROL}>
          {LAYOUTS.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
      </label>
      <input
        placeholder="Search files / functions…"
        style={{ ...CONTROL, flex: 1, maxWidth: 360 }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && props.graphId) props.onSearch((e.target as HTMLInputElement).value)
        }}
      />
    </div>
  )
}
