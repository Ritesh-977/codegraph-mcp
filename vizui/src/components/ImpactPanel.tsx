import type { ImpactPayload } from '../types'

export interface ImpactPanelProps {
  impact: ImpactPayload | null
  loading: boolean
  onClose: () => void
}

export function ImpactPanel({ impact, loading, onClose }: ImpactPanelProps) {
  if (!impact && !loading) return null
  return (
    <aside style={{ width: 320, borderRight: '1px solid #2b3441', overflow: 'auto', background: 'rgba(120,40,40,0.15)', padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong style={{ fontSize: 13 }}>Blast radius: {impact?.seed_path ?? '…'}</strong>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#9aa4b1', cursor: 'pointer' }}>✕</button>
      </div>
      <p style={{ fontSize: 12, color: '#ef9a9a' }}>
        {impact?.callers.length ? `${impact.callers.length} function(s) call in (defined in other files). ` : ''}
        {impact?.truncated ? 'Results truncated at the per-category cap.' : ''}
      </p>
      {impact?.rings.map((ring) => (
        <section key={ring.hop} style={{ fontSize: 12, marginBottom: 8 }}>
          <strong style={{ color: '#ef5350' }}>Hop {ring.hop}</strong>
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {ring.paths.map((p) => <li key={p}>{p}</li>)}
          </ul>
        </section>
      ))}
    </aside>
  )
}
