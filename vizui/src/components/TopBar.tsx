import type { LayoutName } from './GraphCanvas'
import type { RepoInfo } from '../types'

export interface TopBarProps {
  repos: RepoInfo[]
  graphId: string | null
  view: 'overview' | 'full'
  layout: LayoutName
  onRepo: (id: string) => void
  onView: (view: 'overview' | 'full') => void
  onLayout: (l: LayoutName) => void
  onSearch: (q: string) => void
}

const LAYOUTS: { value: LayoutName; label: string }[] = [
  { value: 'architecture', label: 'Architecture (layered)' },
  { value: 'fcose', label: 'Force-directed' },
  { value: 'concentric', label: 'Concentric' },
  { value: 'breadthfirst', label: 'Breadth-first' },
]

export function TopBar(props: TopBarProps) {
  return (
    <header className="topbar">
      <span className="topbar__brand">codegraph</span>

      <select
        className="control"
        value={props.graphId ?? ''}
        onChange={(e) => props.onRepo(e.target.value)}
        aria-label="Repository"
      >
        <option value="" disabled>Select repository…</option>
        {props.repos.map((r) => (
          <option key={r.graph_id} value={r.graph_id}>{r.graph_id}</option>
        ))}
      </select>

      <label className="field">
        Scope
        <select
          className="control"
          value={props.view}
          onChange={(e) => props.onView(e.target.value as 'overview' | 'full')}
        >
          <option value="overview">Directories</option>
          <option value="full">All files</option>
        </select>
      </label>

      <label className="field">
        Layout
        <select
          className="control"
          value={props.layout}
          onChange={(e) => props.onLayout(e.target.value as LayoutName)}
        >
          {LAYOUTS.map((l) => (
            <option key={l.value} value={l.value}>{l.label}</option>
          ))}
        </select>
      </label>

      <span className="topbar__spacer" />

      <input
        className="control control--search"
        placeholder="Search files…  ⏎ to focus"
        aria-label="Search files"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && props.graphId) props.onSearch((e.target as HTMLInputElement).value)
        }}
      />
    </header>
  )
}
