import type { FileDetail } from '../types'
import { highlightLine } from './highlight'

export interface DetailPanelProps {
  detail: FileDetail | null
  loading: boolean
  onClose: () => void
  onFocusPath: (path: string) => void
  onImpact: () => void
}

export function DetailPanel({ detail, loading, onClose, onFocusPath, onImpact }: DetailPanelProps) {
  if (!detail && !loading) return null
  return (
    <aside className="panel panel--right">
      <div className="panel__head">
        <div style={{ minWidth: 0 }}>
          <div className="panel__title">File</div>
          <div className="panel__path">{detail?.path ?? 'Loading…'}</div>
        </div>
        <button className="btn btn--ghost" onClick={onClose} aria-label="Close">✕</button>
      </div>

      {detail && (
        <>
          <div className="panel__section">
            <div className="meta">
              <span><span className="meta__k">lang</span> <span className="meta__v">{detail.language ?? '—'}</span></span>
              <span><span className="meta__k">lines</span> <span className="meta__v">{detail.end_line}</span></span>
              <span><span className="meta__k">last</span> <span className="meta__v">{detail.last_author ?? 'no history'}</span></span>
            </div>
            <div style={{ marginTop: 12 }}>
              <button className="btn" onClick={onImpact}>What breaks if I change this?</button>
            </div>
          </div>

          <div className="panel__section">
            <div className="section__head" style={{ cursor: 'default' }}>
              <span>Imported by</span>
              <span className="section__count">{detail.imported_by.length}</span>
            </div>
            <div className="rows section__body">
              {detail.imported_by.map((p) => (
                <button key={p} className="row" onClick={() => onFocusPath(p)} title={p}>
                  <span className="row__path">{p}</span>
                </button>
              ))}
              {!detail.imported_by.length && <p className="empty">Nothing imports this file.</p>}
            </div>
          </div>

          <div className="panel__section">
            <div className="section__head" style={{ cursor: 'default' }}>
              <span>Imports</span>
              <span className="section__count">{detail.imports.length + detail.external_symbols.length}</span>
            </div>
            <div className="rows section__body">
              {detail.imports.map((p) => (
                <button key={p} className="row" onClick={() => onFocusPath(p)} title={p}>
                  <span className="row__path">{p}</span>
                </button>
              ))}
              {detail.external_symbols.map((s) => (
                <div key={`x:${s}`} className="row" style={{ cursor: 'default' }}>
                  <span className="row__path">{s}</span>
                  <span className="badge badge--import">external</span>
                </div>
              ))}
            </div>
          </div>

          <div className="panel__section">
            <div className="section__head" style={{ cursor: 'default' }}>
              <span>Defines</span>
              <span className="section__count">{detail.functions.length}</span>
            </div>
            <div className="rows section__body">
              {detail.functions.map((f) => (
                <div key={`${f.qualified_name}:${f.start_line}`} className="row" style={{ cursor: 'default' }}>
                  <span className="row__path">{f.name}</span>
                  <span className="row__metric">{f.start_line}–{f.end_line}</span>
                </div>
              ))}
              {!detail.functions.length && <p className="empty">No functions parsed.</p>}
            </div>
          </div>

          <div className="panel__section">
            <div className="section__head" style={{ cursor: 'default' }}>
              <span>Source</span>
              {detail.truncated && <span className="badge badge--hidden">truncated</span>}
            </div>
            <pre className="source section__body">
              {detail.content.split('\n').map((line, i) => (
                <div className="source__line" key={detail.start_line + i}>
                  <span className="source__no">{detail.start_line + i}</span>
                  <span>{highlightLine(line)}</span>
                </div>
              ))}
            </pre>
          </div>
        </>
      )}
    </aside>
  )
}
