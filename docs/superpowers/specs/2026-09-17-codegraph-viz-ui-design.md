# codegraph-viz — Interactive Codebase Relationship Browser

**Date:** 2026-09-17
**Status:** Draft (approved design, awaiting implementation plan)
**Scope:** Add a local web application that visualizes the codegraph Neo4j graph —
files, dependencies, imports, calls — as an interactive, zoomable canvas with
arrows showing data flow between files.

## 1. Why

`codegraph-mcp` ingests a repo into a Neo4j knowledge graph and exposes it as
read-only MCP tools. That is a text-first interface: an LLM reasons over
returned JSON. A human reading a codebase wants the same relationships **seen** —
"what depends on what", "where does this file come from / go to", "what breaks
if I change this" — laid out on a screen they can pan, zoom, and click.

This spec adds `codegraph viz`, a local web app (browser) that renders the
existing graph. No new ingestion, no new parsing, no schema changes — it is a
read-only *view* over the Neo4j data, plus a thin query layer.

## 2. Requirements (decided with the user)

- **Form factor:** local web app opened in a browser, driven by a small
  Python web backend talking to Neo4j.
- **Granularity:** file-level graph on the canvas; functions appear via
  drill-down (detail panel) — not as co-rendered canvas nodes.
- **Scale:** repos of 5,000+ files must remain usable. This drives the
  rendering tech (canvas/WebGL-strength, clustering, zoom-gated labels).
- **Must have (v1):** zoom/pan + zoom-gated labels; neighborhood highlight +
  directional arrows; search + focus; impact/blast-radius panel; directory
  clusters + minimap; detail panel with source preview.
- **Stack:** FastAPI backend + Node/Vite + React + Cytoscape.js frontend.

## 3. Non-goals

- No code editing, writing, or ingestion from the UI. **Read-only.**
- No new node labels or edge types; no Neo4j schema changes.
- No MCP protocol changes. The MCP stdio server is untouched; `codegraph viz`
  is a separate process. `stdout` of the MCP server remains pure JSON-RPC.
- No cross-repo analysis in v1 (pick one repo at a time).

## 4. Architecture

```
browser (React + Cytoscape.js)
   │  HTTP/JSON
   ▼
FastAPI (uvicorn)  ──  `codegraph viz` subcommand, read-only
   │  wraps existing Neo4jAdapter (Bolt) + source_reader (on-disk clone cache)
   ▼
Neo4j (bolt://localhost:7687)        repos/<owner>__<name>/  clone cache
```

### 4.1 New package: `src/codegraph/viz/`

| Module | Responsibility |
|---|---|
| `viz/api.py` | FastAPI app factory; endpoint handlers; error → `{"detail", "hint"}` |
| `viz/service.py` | Query layer wrapping `Neo4jAdapter`; maps adapter results → UI wire format |
| `viz/clustering.py` | Pure functions: aggregate files into directory-cluster nodes + inter-cluster edges |

### 4.2 New CLI subcommand

- `codegraph viz` (`src/codegraph/cli.py`) — boot uvicorn serving the API and
  the built frontend from `vizui/dist/`. When `dist/` is absent, serve the
  API only and print a hint to run `make viz-build`.
- New config (`config.py` + `.env.example`): `VIZ_HOST` (default `127.0.0.1`),
  `VIZ_PORT` (default `8787`).

### 4.3 Frontend: `vizui/`

- Vite + React + TypeScript + **Cytoscape.js** (canvas renderer, built for
  large graphs). Dark theme by default.
- Dev mode: Vite dev server proxies `/api` → FastAPI; production build in
  `vizui/dist/` is served statically by FastAPI.

### 4.4 Commands / Makefile

| Target | Command |
|---|---|
| `make viz` | `uv run codegraph viz` |
| `make viz-dev` | FastAPI + Vite dev servers (concurrent) |
| `make viz-build` | Vite production build into `vizui/dist/` |

## 5. Backend API

All endpoints read-only, all Cypher parameterized and `graph_id`-scoped
(project rule). Errors are JSON `{"detail": <message>, "hint": <what to do next>}`.

| Endpoint | Purpose |
|---|---|
| `GET /api/repos` | Repo picker (uses `list_repos`). |
| `GET /api/graph/{graph_id}?view=overview\|full` | `overview`: directory-clustered graph. `full`: all non-deleted `File` nodes + `IMPORTS` edges (File→File and File→Symbol), capped (>10k edges → `truncated:true` + hint to use overview). |
| `POST /api/subgraph` | Neighborhood: `{graph_id, seed_path, direction, depth, include_symbols}`. |
| `POST /api/impact` | Blast-radius: `{graph_id, seed_path, max_hops}` — reuses `find_file_dependencies` logic; returns subgraph of transitive importers + callers. |
| `GET /api/search?graph_id=&q=&kind=` | Across `search_nodes`; frontend focuses canvas on best match. |
| `GET /api/file/{graph_id}/{path}` | Detail panel: metadata (`get_file_info`) + source text (`source_reader`) + functions defined with line ranges + import/caller lists. |

### 5.1 Wire format (UI schema, independent of MCP pydantic models)

```json
{
  "graph_id": "owner/name",
  "view": "overview",
  "nodes": [
    {"id": "dir:src", "kind": "dir_cluster", "label": "src", "file_count": 42, "language": null},
    {"id": "file:src/a.py", "kind": "file", "label": "a.py", "path": "src/a.py", "language": "python"}
  ],
  "edges": [
    {"source": "dir:src", "target": "dir:lib", "type": "IMPORTS", "weight": 7}
  ],
  "stats": {"file_count": 5200, "edge_count": 18200, "truncated": true, "view": "overview"}
}
```

Node kinds: `file`, `dir_cluster`, `symbol`, `function`. Edge types seen by the
UI: `IMPORTS`, `CALLS`, `DEFINES`, plus `IMPORTS` aggregated between clusters.
`full` view carries `file` + `symbol` nodes and `IMPORTS` edges only; `CALLS`/
`DEFINES` and functions appear in subgraph/impact/detail results.

## 6. Frontend behavior

- **Zoom/pan + zoom-gated labels**: labels hidden until zoom passes a
  threshold; hover always shows label via tooltip.
- **Neighborhood highlight**: click node → outgoing (imports) blue, incoming
  (imported_by) red, others dimmed; directional arrowheads on edges.
- **Flow animation**: on hover/select, edges animate as moving particles so
  data flow to/from the file is visible.
- **Search**: top bar → `/api/search` → Enter centers on best match.
- **Directory clusters/minimap**: overview starts as dir-cluster nodes
  (cytoscape compound nodes + expand/collapse); minimap in corner.
- **Detail panel** (right): language, path, last author/commit, line count;
  tabs — Source (highlighted), Dependents (imported_by), Imports,
  Functions defined (click function → jump to its lines).
- **Impact panel**: button on selected file → `/api/impact` → red overlay
  subgraph of everything that would break.
- **Layouts**: switchable `fcose` (default), `concentric` (hub files center),
  `breadthfirst` (layer by depth) for overview.

## 7. Performance (5k+ files)

- First load is always `overview` (clustered) — small payload, fast layout.
  `full` is opt-in and size-capped server-side.
- Cytoscape canvas renderer + zoom-gated labels keep DOM cost flat.
- Expand-on-demand: clusters expand one level at a time; subgraph/impact
  queries stay depth-limited and are always user-triggered, never on load.
- Layout params scale with node count (collision radius, spacing).

## 8. Error handling & testing

- Errors: `{"detail", "hint"}` everywhere; no stack traces surfaced to the UI.
- Backend unit tests: `viz/clustering.py` (pure functions) and `viz/service.py`
  against a fake adapter; integration tests with testcontainers Neo4j (fresh
  `graph_id` per test) for happy + at least one error path per endpoint;
  FastAPI `TestClient` for URL/app routing.
- Frontend: Vitest for graph-data mapping (adapter rows → cytoscape JSON).
- E2E smoke: boot `codegraph viz`, assert `/api/repos` + `/api/graph` return
  200 against a fixture test repo.
- Docs: README section + Makefile targets wired into
  `make lint typecheck test` gates (viz Python code included in lint/typecheck).

## 9. Design principles honored

- Every Cypher query parameterized and `WHERE n.graph_id = $graph_id`.
- Server reads Neo4j only; no writes, no destructive tools.
- MCP stdio stays pure JSON-RPC; `codegraph viz` is a separate process.
- Tool-error philosophy extended: API errors are plain-text guidance, never
  stack traces.
- Tests run offline on fixtures; DB tests via testcontainers.