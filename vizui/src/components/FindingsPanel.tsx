import { useState } from 'react'
import type { Findings, FindingKind, Highlight } from '../types'

export interface FindingsPanelProps {
  findings: Findings | null
  loading: boolean
  active: FindingKind | null
  onHighlight: (h: Highlight | null) => void
  onFocusPath: (path: string) => void
}

const fileId = (p: string) => `file:${p}`

function Section({
  title, count, kind, active, children, onToggle,
}: {
  title: string
  count: number
  kind: FindingKind
  active: boolean
  children: React.ReactNode
  onToggle: (kind: FindingKind) => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className="panel__section">
      <button
        className="section__head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span>{open ? '▾' : '▸'}</span>
        <span>{title}</span>
        <span className="section__count">{count}</span>
        <span className="topbar__spacer" />
        <span
          role="button"
          tabIndex={0}
          className={`btn btn--ghost${active ? ' btn--active' : ''}`}
          onClick={(e) => {
            e.stopPropagation()
            onToggle(kind)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.stopPropagation()
              onToggle(kind)
            }
          }}
        >
          {active ? 'hide' : 'show'}
        </span>
      </button>
      {open && <div className="section__body">{children}</div>}
    </div>
  )
}

export function FindingsPanel(props: FindingsPanelProps) {
  const { findings: f, loading, active, onHighlight, onFocusPath } = props

  if (loading && !f) {
    return (
      <aside className="panel panel--left">
        <div className="panel__head"><span className="panel__title">Findings</span></div>
        <div className="panel__section empty">Analysing graph…</div>
      </aside>
    )
  }
  if (!f) return null

  const toggle = (kind: FindingKind, build: () => Highlight) =>
    onHighlight(active === kind ? null : build())

  const maxHub = f.hubs[0]?.dependents ?? 1

  return (
    <aside className="panel panel--left">
      <div className="panel__head">
        <span className="panel__title">Findings</span>
      </div>

      <div className="stats">
        <div className="stat">
          <div className="stat__value">{f.file_count}</div>
          <div className="stat__label">files</div>
        </div>
        <div className="stat">
          <div className="stat__value">{f.max_layer + 1}</div>
          <div className="stat__label">layers deep</div>
        </div>
        <div className={`stat ${f.cycles.length ? 'stat--critical' : 'stat--good'}`}>
          <div className="stat__value">{f.cycles.length}</div>
          <div className="stat__label">cycles</div>
        </div>
      </div>

      <Section
        title="Hubs" count={f.hubs.length} kind="hubs" active={active === 'hubs'}
        onToggle={() => toggle('hubs', () => ({ kind: 'hubs', ids: f.hubs.slice(0, 8).map((h) => fileId(h.path)) }))}
      >
        <p className="hint" style={{ marginTop: 0 }}>Most depended-upon — the riskiest files to change.</p>
        <div className="rows">
          {f.hubs.map((h) => (
            <button key={h.path} className="row" onClick={() => onFocusPath(h.path)} title={h.path}>
              <span className="row__bar"><i style={{ width: `${(h.dependents / maxHub) * 100}%` }} /></span>
              <span className="row__metric">{h.dependents}</span>
              <span className="row__path">{h.path}</span>
            </button>
          ))}
          {!f.hubs.length && <p className="empty">No file has dependents.</p>}
        </div>
      </Section>

      <Section
        title="Entry points" count={f.entry_points.length} kind="entries" active={active === 'entries'}
        onToggle={() => toggle('entries', () => ({ kind: 'entries', ids: f.entry_points.map(fileId) }))}
      >
        <p className="hint" style={{ marginTop: 0 }}>Nothing imports these — start reading here.</p>
        <div className="rows">
          {f.entry_points.map((p) => (
            <button key={p} className="row" onClick={() => onFocusPath(p)} title={p}>
              <span className="row__path">{p}</span>
            </button>
          ))}
        </div>
      </Section>

      <Section
        title="Orphans" count={f.orphans.length} kind="orphans" active={active === 'orphans'}
        onToggle={() => toggle('orphans', () => ({ kind: 'orphans', ids: f.orphans.map(fileId) }))}
      >
        <p className="hint" style={{ marginTop: 0 }}>
          <span className="badge badge--hidden">⚠ check</span>{' '}
          No imports in or out — dead code, or reached some other way.
        </p>
        <div className="rows">
          {f.orphans.map((p) => (
            <button key={p} className="row" onClick={() => onFocusPath(p)} title={p}>
              <span className="row__path">{p}</span>
            </button>
          ))}
          {!f.orphans.length && <p className="empty">None — every file is connected.</p>}
        </div>
      </Section>

      <Section
        title="Cycles" count={f.cycles.length} kind="cycles" active={active === 'cycles'}
        onToggle={() =>
          toggle('cycles', () => ({
            kind: 'cycles',
            critical: true,
            ids: f.cycles.flatMap((c) => c.paths.map(fileId)),
          }))
        }
      >
        {f.cycles.length ? (
          <div className="rows">
            {f.cycles.map((c) => (
              <div key={c.paths.join('|')} style={{ marginBottom: 8 }}>
                <span className="badge badge--critical">✕ {c.paths.length} files</span>
                {c.paths.map((p) => (
                  <button key={p} className="row" onClick={() => onFocusPath(p)} title={p}>
                    <span className="row__path">{p}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        ) : (
          <p className="empty">
            <span className="badge badge--good">✓ clean</span> No circular imports.
          </p>
        )}
      </Section>

      <Section
        title="Change coupling" count={f.coupling.length} kind="coupling" active={active === 'coupling'}
        onToggle={() =>
          toggle('coupling', () => ({
            kind: 'coupling',
            ids: f.coupling.flatMap((c) => [fileId(c.a), fileId(c.b)]),
            pairs: f.coupling
              .filter((c) => !c.has_import_edge)
              .map((c) => [fileId(c.a), fileId(c.b)] as [string, string]),
          }))
        }
      >
        <p className="hint" style={{ marginTop: 0 }}>
          Files that keep changing in the same commit. A{' '}
          <span className="badge badge--hidden">hidden</span> pair has no import between
          them — coupling the code does not admit to.
        </p>
        {f.coupling_available ? (
          <div className="rows">
            {f.coupling.map((c) => (
              <button
                key={`${c.a}|${c.b}`}
                className="row"
                onClick={() => onFocusPath(c.a)}
                title={`${c.a}\n${c.b}`}
              >
                <span className="row__metric">{c.shared_commits}×</span>
                <span className={`badge ${c.has_import_edge ? 'badge--import' : 'badge--hidden'}`}>
                  {c.has_import_edge ? 'import' : 'hidden'}
                </span>
                <span className="row__path">
                  {c.a.split('/').pop()} ↔ {c.b.split('/').pop()}
                </span>
              </button>
            ))}
            {!f.coupling.length && <p className="empty">No pair changes together often enough.</p>}
          </div>
        ) : (
          <p className="empty">{f.coupling_hint}</p>
        )}
      </Section>
    </aside>
  )
}
