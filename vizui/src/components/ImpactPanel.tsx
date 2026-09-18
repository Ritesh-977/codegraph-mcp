import type { ImpactPayload } from '../types'

export interface ImpactPanelProps {
  impact: ImpactPayload | null
  loading: boolean
  onClose: () => void
  onFocusPath: (path: string) => void
}

export function ImpactPanel({ impact, loading, onClose, onFocusPath }: ImpactPanelProps) {
  if (!impact && !loading) return null
  const total = impact?.rings.reduce((n, r) => n + r.paths.length, 0) ?? 0
  return (
    <aside className="panel panel--left">
      <div className="panel__head">
        <div>
          <div className="panel__title">Blast radius</div>
          <div className="panel__path">{impact?.seed_path ?? '…'}</div>
        </div>
        <button className="btn btn--ghost" onClick={onClose} aria-label="Close">✕</button>
      </div>

      {impact && (
        <>
          <div className="stats" style={{ gridTemplateColumns: 'repeat(2, 1fr)' }}>
            <div className="stat stat--warning">
              <div className="stat__value">{total}</div>
              <div className="stat__label">files reached</div>
            </div>
            <div className="stat">
              <div className="stat__value">{impact.callers.length}</div>
              <div className="stat__label">calling functions</div>
            </div>
          </div>
          {impact.truncated && (
            <div className="panel__section">
              <p className="hint" style={{ marginTop: 0 }}>
                <span className="badge badge--hidden">⚠</span> Results hit the per-category cap —
                narrow the hop count for an exact list.
              </p>
            </div>
          )}
          {impact.rings.map((ring) => (
            <div className="panel__section" key={ring.hop}>
              <div className="section__head" style={{ cursor: 'default' }}>
                <span>Hop {ring.hop}</span>
                <span className="section__count">{ring.paths.length}</span>
              </div>
              <div className="rows section__body">
                {ring.paths.map((p) => (
                  <button key={p} className="row" onClick={() => onFocusPath(p)} title={p}>
                    <span className="row__path">{p}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </>
      )}
    </aside>
  )
}
