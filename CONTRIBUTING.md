# Contributing to codegraph-mcp

This document is the single source of truth for scope, architecture, and conventions.

## 1. Architecture (three-phase split)

1. **Ingestion (CLI, offline):** `codegraph ingest <url>` clones, walks, parses
   (Python `ast` + tree-sitter for JS/TS), collects commit metadata, and writes
   parameterized Cypher `MERGE`s to Neo4j under a per-repo `graph_id`.
2. **MCP server (stdio):** a FastMCP server exposes 6 read-only tools + 2 resources
   that query the same Neo4j. It never clones, parses, or writes.
3. **MCP host:** Claude Desktop / opencode / Cursor spawns the server via `mcpServers`
   config; the LLM calls tools to answer developer questions.

Neo4j is the only durable store. The server holds no graph state in memory.

## 2. Conventions (hard rules)

- **Every Cypher query MUST be parameterized and filter `WHERE n.graph_id = $graph_id`.**
- **stdio transport rule:** server MUST NOT write anything to stdout except valid MCP
  messages. All logging goes to stderr.
- **No write tools exposed to the LLM.** Ingestion is CLI-only.
- **Tool errors are LLM-readable:** surface "what to do next" text, never stack traces.
  Two tiers: malformed args → JSON-RPC `-32602` (SDK-handled via pydantic);
  business/DB errors → `ToolError` with plain-text guidance.
- **Soft-delete tombstones** for pruned files (`deleted=true`); hard-wipe is CLI-only
  via `codegraph reset --graph-id X`.
- **Repo slug = `graph_id`** (e.g. `owner/name`); enforced in every Cypher statement.
- **File paths are repo-relative POSIX** (forward slashes) regardless of OS.
- **JS/TS qualified_names are file-scoped** (`path::funcname`) to avoid cross-file
  collisions; Python uses dotted qnames (`Class.method`).
- **Tests run offline** — no real GitHub clones; tests use `tests/fixtures/` repos.
  Neo4j-backed tests use `testcontainers-python` with a fresh `graph_id` per test.

## 3. Testing Strategy

| Layer | Scope |
|---|---|
| **unit** | Pure logic: parsers, walker, resolver, Cypher string assertions, model validation |
| **integration** | Neo4j-backed via testcontainers-python; tool module happy + error paths |
| **contract** | Golden snapshot of tool names + descriptions |
| **e2e** | Server smoke: all 6 tools + 2 resources registered |

### CI gates (every push)

- `ruff check src tests`
- `mypy src`
- `pytest -m "not slow and not integration"`
- Contract snapshot diff passes

## 4. CLI Reference

| Command | Purpose |
|---|---|
| `codegraph ingest <url>` | Clone + parse + load into Neo4j |
| `codegraph serve` | Run MCP server (stdio) |
| `codegraph reset --graph-id X` | Hard-wipe one repo (destructive) |
| `codegraph ls` | List ingested repos |

## 5. Glossary

| Term | Definition |
|---|---|
| **MCP** | Model Context Protocol — open standard for LLM ↔ tool communication |
| **JSON-RPC** | Wire protocol MCP rides on (2.0) |
| **stdio transport** | Client spawns server as subprocess; JSON-RPC over stdin/stdout |
| **FastMCP** | Python MCP SDK's high-level server framework (v1.x stable) |
| **graph_id** | Per-repo isolation key (owner/name); enforced in every Cypher query |
| **Bolt** | Neo4j's binary protocol (port 7687) |
| **Cypher** | Neo4j's declarative graph query language |
| **Soft-delete tombstone** | `deleted=true` flag on File nodes; never hard-deleted by tools |
| **tree-sitter** | Incremental parsing library; used for JS/TS/TSX |
