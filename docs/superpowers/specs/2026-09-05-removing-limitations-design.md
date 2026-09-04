# Removing codegraph-mcp Limitations — Roadmap & Design

**Date:** 2026-09-05
**Status:** Draft (proposed roadmap)
**Scope:** Turn the current read-only, Python+JS/TS impact-analysis server into a broadly adoptable code-intelligence platform by removing every known limitation.

## 1. Why

`codegraph-mcp` ingests a GitHub repo into a Neo4j knowledge graph and exposes
read-only MCP tools over it. In its current form it answers one class of
question well: *"what depends on X in a single Python/JS/TS repo?"*

A senior engineer evaluating it for a real company project would hit hard
blocks that make them pick a file-reading MCP server or a vendor product instead:

1. **It cannot return source code.** Every tool returns metadata (names, paths,
   line ranges) but never the code text — so an agent can "know about" a
   function but can't read, review, or reason about its body.
2. **It supports 4 languages** and skips most of a mixed-stack company's code.
3. **It cannot ingest private repositories**, which is where company code lives.
4. **It is effectively single-hop** on its flagship query (`max_hops` is inert),
   and several advertised knobs don't work.
5. **No cross-repo analysis**, though the stated project vision includes it.

This roadmap removes those blocks in six ordered phases, each independently
deliverable and testable.

## 2. Current state (baseline)

- Two processes: offline `codegraph` CLI (ingest/reset/ls/serve) + FastMCP
  stdio server exposing 6 read-only tools + 2 resources.
- Schema: `Repository -CONTAINS-> File -DEFINES-> Function`,
  `File -IMPORTS-> File|Symbol`, `Function -CALLS-> Function|Symbol`; every node
  carries `graph_id` (= repo slug) for multi-repo isolation; `File` uses a
  `deleted` tombstone for pruned files.
- Parsers: Python `ast`, tree-sitter for JS/TS/TSX.
- Tools: `list_repos`, `init_repository_node`, `get_repo_structure`,
  `find_file_dependencies`, `search_nodes`, `get_node_detail`.
- Tests: unit / integration (testcontainers Neo4j) / contract snapshots / e2e.

## 3. Global design principles (apply to every phase)

- **Every Cypher query stays parameterized and `graph_id`-scoped.** No literal
  interpolation of values; relationship-type literals remain regex-validated.
- **The MCP server stays read-only to the LLM.** All ingestion/writes remain
  offline CLI-side. New tools must be read-only.
- **stdio rule preserved:** server logs to `stderr` only; `stdout` stays pure
  JSON-RPC.
- **Every new tool** needs a pydantic input model in `src/codegraph/models/`,
  a thin module in `src/codegraph/tools/`, a unit test for validation, and an
  integration test for happy + at least one `isError:true` path.
- **Any new node label / edge type** needs a design-spec entry and a contract
  snapshot update.
- **Tests run offline** (fixtures, no network clones); DB tests use
  testcontainers with a fresh `graph_id` per test.

---

## Phase 1 — Finish Tier-1 features (Basic; Low effort; safe quick wins)

Delivery goal: no advertised-but-dead behavior; clean code; accurate counts.

### 1.1 Implement `max_hops` traversal
- Replace the five hardcoded single-hop queries in `Neo4jAdapter.find_file_dependencies`
  with Cypher variable-length paths (`[*1..$max_hops]`).
- Populate the result `hop` from `length(path)` instead of constant `1`.
- Cap result sets to avoid runaway expansion on `max_hops=4` (respect `limit`/
  truncation semantics already present in the result model).
- Keep the existing filter semantics (respect `deleted` tombstones, direction).
- **Why:** the flagship *"what breaks transitively?"* question is currently
  unanswerable.

### 1.2 Validate `direction` and `search_nodes.kind` as enums
- Change `FindFileDependenciesArgs.direction` to a `Literal["imports","imported_by",
  "both"]` and `SearchNodesArgs.kind` to `Literal["any","function","file"]`
  (pydantic → automatic JSON-RSC `-32602` on invalid input).
- Fix the asymmetric `external_symbols` body so it no longer runs
  unconditionally regardless of `direction`.
- **Why:** silent empty results on typos are the worst failure mode for an LLM
  consumer.

### 1.3 Wire up `--force` and `INGEST_BATCH_SIZE`
- `--force`: pass through to `clone_or_fetch` to remove the local cache and
  re-clone fresh.
- `INGEST_BATCH_SIZE`: batch the `run_plan` write statements into
  transactions / batched `UNWIND` MERGEs (also gives resumability later).
- **Why:** both knobs are advertised but dead; force fixes corrupt caches,
  batching fixes large-repo ingest performance.

### 1.4 Clean stale code & fix counting
- Refresh `Neo4jAdapter` docstring (read methods are all implemented).
- Remove unused `_REL_TYPE_RE`.
- `init_repository_node` and `get_node_detail`: exclude tombstoned (`deleted=true`)
  files from counts and addressability for consistency.
- **Why:** trust and accuracy; undead/tombstoned nodes and inflated counts
  mislead the LLM.

---

## Phase 2 — Source-code retrieval (Medium effort; biggest real-world need)

Delivery goal: an agent can read actual code, not just metadata about it.

### 2.1 Persist source text at ingest
- Store file content / per-function line slices in the graph (e.g., `File.body`
  property, or a content blob store / sidecar files under `repos_dir`) keyed by
  `(graph_id, path)` and versioned by commit SHA when available.
- Decide storage trade-off: inline property (simple, small repos) vs. external
  filesystem/blob (scales, avoids giant DB rows). Recommend external store with
  the graph holding pointers.
- Keep read-only server access semantics.

### 2.2 New tools
- `get_file_content(graph_id, file_path, range?)` — return code text, honoring
  the `deleted` tombstone and POSIX path normalization.
- `get_function_source(graph_id, node_id)` — return the function body by line
  range, reusing `search_nodes`/`get_node_detail` IDs.
- Both return LLM-readable `TextContent` plus a `structuredContent` model.

### 2.3 Why
Without code text a knowledge graph is a map with no roads — the #1 reason a
dev abandons this for a plain file reader. This is the highest-value change.

---

## Phase 3 — More languages (High effort; incremental per language)

Delivery goal: cover the languages a mixed-stack company actually uses.

### 3.1 Language matrix (each = one mini-phase)
Start with the highest-demand, then expand on feedback:
1. Go
2. Java / Kotlin
3. C / C++ / C#
4. Rust
5. (Long tail: Ruby, PHP, Swift, TypeScript already covered)

Each language needs:
- A tree-sitter grammar + source parser producing the existing
  `ExtractedFunction/Import/Call` DTOs.
- An import resolver (module → repo-relative file) for that language's module
  system.
- Extension → language mapping in `walker.py`.
- Unit tests (+ one fixture per language) and an integration e2e.

### 3.2 Why
A single-language tool can't serve a real company project. Language support is
one of the two biggest adoption gates (with private-repo auth).

---

## Phase 4 — Parser depth (High effort; accuracy)

Delivery goal: the graph is accurate, not just present.

### 4.1 JS/TS depth
- Capture arrow functions (`() => {}`), `export default`, object-literal methods,
  namespace/destructured imports, and alias tracking.
- Fix nested-caller resolution (currently collapses to outermost function).
- **Why:** modern JS/TS is dominated by arrow functions and default exports;
  without them most of a frontend call graph is invisible.

### 4.2 Python call resolution
- Track the receiver object and its inferred type (from class definitions,
  imports, and available type hints) to disambiguate `obj.method()` calls instead
  of bare-name string-suffix matching with first-match-wins.
- **Why:** naive resolution yields wrong impact answers for common/overloaded
  method names.

### 4.3 Validation
- Accuracy is only meaningful if measured: add a "resolution accuracy" check on
  a known fixture and keep it as a regression test.

---

## Phase 5 — Richer queries (Low→High effort; new tools)

Delivery goal: answer more of the questions a developer actually asks.

### 5.1 Commit / author queries (Low)
- Expose stored per-file `last_author`, `last_commit_at`, `last_commit_sha` via a
  new tool (e.g., extend `get_node_detail` or add `get_file_metadata`).
- **Why:** "who owns / last touched this code" and recency are core triage
  questions and the data is already stored but unused.

### 5.2 Cross-repo / multi-repo analysis (High)
- Add inter-repo dependency edges derived from package manifests / cross-repo
  imports at ingest.
- Add a multi-repo tool that traverses across `graph_id` boundaries.
- **Why:** monorepos, shared libraries, and dependent services are normal;
  cross-repo impact is exactly what a Neo4j graph is uniquely suited for, and it
  is in the stated project vision.

### 5.3 Better search (Medium)
- Use Neo4j full-text indexes (`db.index.fulltext`) for scored, ranked
  `search_nodes` instead of constant-`1.0` substring `CONTAINS`.
- Add pagination (offset) for large result sets.
- **Why:** large repos need relevance ranking and paging.

---

## Phase 6 — Operational robustness (Medium→High effort; production polish)

Delivery goal: usable at company scale with real code and real cadence.

### 6.1 Atomic / resumable ingest
- Wrap the ingest plan in a transaction (all-or-nothing) or batched,
  resumable chunks with progress reporting.
- **Why:** large-repo ingests must not leave partial graphs or redo everything.

### 6.2 Private-repo & authenticated access
- Support git auth (token / SSH / credential helpers) for private repos and
  self-hosted git hosts (GitLab, Bitbucket, Gitea).
- Treat credentials as a security-sensitive surface: read from env/secrets,
  never logged, never written to the graph.
- **Why:** company code is private; without auth this tool cannot be used on
  real internal projects. (Highest-priority with #3 for adoption, and the most
  security-critical.)

### 6.3 Automated refresh / discovery
- Scheduled or event-driven re-ingest (scheduler, CLI `cron`, or a CI step) so
  the graph tracks a moving codebase.
- Optional repo discovery (from a git host API / config file) instead of manual
  per-repo ingest.
- **Why:** manual ingest doesn't scale past a few repos.

### 6.4 Ops hygiene
- `reset` should also clean the on-disk clone cache.
- `search_nodes` pagination added in Phase 5.5.3.

---

## 4. Vector embeddings strategy

The graph encodes **structure** (exact relations: `CALLS`, `IMPORTS`, `DEFINES`).
Vector embeddings encode **meaning** (fuzzy semantic similarity). They solve
different problems and must not be conflated. The rule: keep the graph as the
single source of truth for structure; treat embeddings as an optional,
*parallel, semantic-only* recall layer.

### 4.1 Where embeddings add real value

| Use case | Embeddings? | Why |
|---|---|---|
| Impact analysis (`find_file_dependencies`) | No | Purely structural; vectors can't express a concrete dependency |
| Call/import resolution | No | Needs precise symbol resolution, not fuzzy matching |
| Node identity / dedup | No | Exact qnames are the correct key |
| Structure, distance, authors | No | All exact-valued |
| **Natural-language code search** (`search_semantic`) | **Yes** | LLM asks "find the code that computes tax" → return `_compute_tax` / `apply_vat`. Invisible to exact-name matching |
| **LLM retrieval (RAG grounding)** | **Yes** | Pull relevant function/file snippets for an agent, layered on Phase 2's code retrieval |

### 4.2 Key constraint: Neo4j Community has no native vector index

- `db.index.vector` (native vector index) is a Neo4j **Enterprise / AuraDB**
  feature. The project runs `neo4j:5-community` (docker-compose), so a Neo4j
  vector index would hit a licensing/enterprise-only error.
- Neo4j **Community does** support full-text indexes
  (`CREATE FULLTEXT INDEX` / APOC), which are sufficient to fix `search_nodes`
  ranking without any embedding machinery.

### 4.3 Storage options

- **Option A — External vector store (recommended default).** Compute
  embeddings offline (sentence-transformers / code model / provider API), store
  them beside the graph (sqlite-vec, Qdrant, Chroma, or plain vector file) keyed
  by node id. A `search_semantic` tool consults the external store → returns
  node ids → the graph resolves those to rich context. Keeps Neo4j purely
  structural and the server read-only; no enterprise license. Downside: one more
  index to keep in sync at ingest.
- **Option B — Neo4j Enterprise / AuraDB.** Native vector + full-text in one
  managed store. Cleaner, but requires Enterprise licensing or AuraDB; heavier
  ops lift than the current stack.
- **Option C — Skip embeddings; use native full-text first.** Community full
  text fixes `search_nodes` scoring/ranking with far less machinery and suits
  code-identifier search (code is mostly exact tokens). Good enough for the
  current tool set.

### 4.4 Recommendation: phase it — don't build embeddings now

1. **Now — skip embeddings.** `search_nodes` is a code-identifier finder;
   exact token + full-text scores beat vectors for it. Keep Neo4j structural,
   read-only, and simple.
2. **Once Phase 2 (code retrieval) exists — add `search_semantic`** backed by
   an **external vector store (Option A)** for natural-language "find code that
   does X". This is the one genuinely valuable embedding use case, and it only
   makes sense once a tool can return the actual code.
3. **Only move to Enterprise/Aura (Option B)** if a managed, single-store
   vector + full-text solution is later worth the cost and ops overhead.

Embeddings deliberately extend — never replace — the structural analysis in
Phases 1/4/5. Building the "code exists" foundation (Phase 2) first is a
prerequisite for embeddings to pay off.

---

## 5. Effort & priority summary

| Phase | Theme | Effort | Adoption impact |
|---|---|---|---|
| 1 | Finish Tier-1 features | Low | Trust/correctness |
| 2 | Source-code retrieval | Medium | **Highest value** |
| 3 | More languages | High | **Gate** |
| 4 | Parser depth | High | Accuracy |
| 5 | Richer queries | Low→High | Capability |
| 6 | Ops robustness (incl. auth) | Medium→High | **Gate** (auth) |

The three adoption gates a real team will hit first: **source-code retrieval
(Phase 2)**, **language support (Phase 3)**, and **private-repo auth (Phase 6)**.
Those should not be deprioritized once the low-risk cleanliness of Phase 1 is
in.

## 6. Open questions (resolved before implementation of each phase)

- Phase 2: inline `File.body` property vs. external blob store — recommend
  external store, confirm at plan time.
- Phase 3: exact initial language set and ordering (company-driven).
- Phase 6.2: which git hosts / auth mechanisms are required; credential storage.
- Phase 5.2: what defines a cross-repo dependency for your use case
  (package manager, import path prefix, manifest).

## 7. Test & documentation strategy

- Each phase adds/updates: unit tests, integration tests (testcontainers,
  fresh `graph_id`), contract snapshots (`make snapshot-update`) when schemas
  change, and e2e smoke when tools are added.
- Per the project conventions: run `make lint typecheck test` before review;
  all three must pass.
- Update `CONTRIBUTING.md` / `PROJECT_OVERVIEW.md` / `README.md` as capabilities
  land (only where they describe scope).
