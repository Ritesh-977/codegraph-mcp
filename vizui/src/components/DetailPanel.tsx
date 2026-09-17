import type { FileDetail } from '../types'
import { highlightLine } from './highlight'

export interface DetailPanelProps {
  detail: FileDetail | null
  loading: boolean
  onClose: () => void
}

export function DetailPanel({ detail, loading, onClose }: DetailPanelProps) {
  if (!detail && !loading) return null
  return (
    <aside style={{ width: 380, borderLeft: '1px solid #2b3441', overflow: 'auto', background: '#12161c', padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong style={{ fontSize: 13 }}>{detail?.path ?? 'Loading…'}</strong>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#9aa4b1', cursor: 'pointer' }}>✕</button>
      </div>
      {detail && (
        <>
          <p style={{ fontSize: 12, color: '#9aa4b1', margin: '6px 0' }}>
            {detail.language} · {detail.last_author ? `last: ${detail.last_author}` : 'no git history'}
          </p>
          <section style={{ fontSize: 12, marginBottom: 10 }}>
            <strong>Imports</strong>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {detail.imports.map((p) => <li key={p}>{p}</li>)}
              {detail.external_symbols.map((s) => <li key={`x:${s}`}>{s} (external)</li>)}
            </ul>
          </section>
          <section style={{ fontSize: 12, marginBottom: 10 }}>
            <strong>Dependents</strong>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {detail.imported_by.map((p) => <li key={p}>{p}</li>)}
            </ul>
          </section>
          <section style={{ fontSize: 12, marginBottom: 10 }}>
            <strong>Functions</strong>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {detail.functions.map((f) => (
                <li key={`${f.qualified_name}:${f.start_line}`}>
                  {f.name} — {f.start_line}–{f.end_line}
                </li>
              ))}
            </ul>
          </section>
          <section>
            <strong>Source{detail.truncated ? ' (truncated)' : ''}</strong>
            <pre style={{ fontSize: 11, background: '#0e1116', padding: 8, borderRadius: 4, overflow: 'auto', maxHeight: 420 }}>
              {detail.content.split('\n').map((line, i) => (
                <div key={detail.start_line + i}>
                  <span style={{ color: '#4a545f', display: 'inline-block', width: 34, userSelect: 'none' }}>
                    {detail.start_line + i}
                  </span>
                  {highlightLine(line)}
                </div>
              ))}
            </pre>
          </section>
        </>
      )}
    </aside>
  )
}
