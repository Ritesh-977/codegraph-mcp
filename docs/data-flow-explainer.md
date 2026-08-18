# Data Flow Explainer — codegraph-mcp

**Purpose:** Trace one prompt from keystroke to answer, showing exactly where the data
goes, how it moves, and what each component does. This is the "how it works behind the
scenes" document.

---

## The Scenario

You've ingested a repo (`codegraph ingest https://github.com/owner/name`). Now you open
Claude Desktop and type:

> "What files will break if I modify `auth_service.py` in the `owner/name` repo?"

Here's what happens, step by step.

---

## Step 1: Claude Desktop spawns the MCP server

When Claude Desktop starts (or when you first send a message that might use codegraph),
it reads its `mcpServers` config and spawns the `codegraph serve` process as a
**subprocess**:

```
Claude Desktop (MCP Host)
  │
  ├── spawns: uv run --directory /path/to/codegraph-mcp codegraph serve
  │
  └── connects to the subprocess via:
        ├── stdin  → writes JSON-RPC requests TO the server
        └── stdout ← reads JSON-RPC responses FROM the server
```

The server process (`src/codegraph/server.py`) does the following on boot:

1. **`app_lifespan`** runs (FastMCP lifespan context manager):
   - Creates `Neo4jAdapter.from_settings(Settings())`
   - Calls `adapter.connect()` — opens a Bolt connection to `bolt://localhost:7687`
   - Calls `adapter.apply_migrations()` — runs 6 idempotent Cypher DDL statements
     (`CREATE CONSTRAINT IF NOT EXISTS` for uniqueness on Repository/File/Function,
     `CREATE INDEX IF NOT EXISTS` for fast lookups)
   - Yields `AppState(adapter=adapter)` to the FastMCP framework
   - Sets `_ACTIVE_STATE` so resource functions can access the adapter

2. **`mcp.run(transport="stdio")`** blocks on `stdin`, waiting for JSON-RPC messages.

**Data flow:**
```
.env file → Settings() → Neo4jAdapter → Bolt connection → Neo4j (localhost:7687)
```

**Critical rule:** The server MUST NOT write anything to `stdout` except valid JSON-RPC
messages. All logging goes to `stderr`. A stray `print()` would corrupt the protocol
stream. This is why `logging_setup.py` uses `StreamHandler(sys.stderr)`.

---

## Step 2: Capability handshake (MCP `initialize`)

Claude Desktop sends an `initialize` JSON-RPC request over the server's stdin:

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize",
 "params": {"protocolVersion": "2025-06-18", "capabilities": {...}}}
```

The FastMCP SDK handles this automatically — it responds with the server's
capabilities (tools + resources) and `serverInfo`. Then the host sends a
`notifications/initialized` notification (no response expected — JSON-RPC
notifications have no `id`).

**Data flow:**
```
Claude Desktop stdin → server stdin → FastMCP SDK → server stdout → Claude Desktop
```

---

## Step 3: Tool discovery (`tools/list`)

Claude Desktop sends `tools/list`. The FastMCP SDK introspects all `@mcp.tool()`
registrations and returns their names, descriptions, and auto-derived `inputSchema`
(from the pydantic type hints — no hand-written JSON Schemas anywhere):

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
```

Response includes all 6 tools:
- `list_repos`, `init_repository_node`, `get_repo_structure`,
- `find_file_dependencies`, `search_nodes`, `get_node_detail`

The LLM now knows what tools are available.

**Data flow:**
```
Claude Desktop → stdin → FastMCP SDK → introspects @mcp.tool() registry
  → stdout → Claude Desktop → LLM context: "these tools are available"
```

---

## Step 4: The LLM grounds itself

Claude reads the `codegraph://repos` resource (a `resources/read` JSON-RPC call) to
learn what repos exist. The resource handler calls `read_repos_resource(adapter)` which
runs:

```cypher
MATCH (r:Repository)
RETURN r.graph_id AS graph_id, r.name AS name, r.url AS url,
       r.default_branch AS default_branch, r.ingested_at AS ingested_at
```

This returns `[{"graph_id": "owner/name", "name": "owner/name", "url": "...", ...}]`.

The LLM now knows `graph_id = "owner/name"`.

**Data flow:**
```
Claude → resources/read → FastMCP → _state().adapter.list_repos()
  → Bolt → Neo4j → MATCH (r:Repository) → results
  → JSON-RPC response → Claude → LLM: "graph_id is owner/name"
```

---

## Step 5: The LLM calls `init_repository_node`

To confirm the repo exists and get counts, the LLM calls `init_repository_node`:

```json
{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
 "params": {"name": "init_repository_node",
            "arguments": {"graph_id": "owner/name"}}}
```

FastMCP calls the `@mcp.tool()` function, which:
1. Gets the adapter from `ctx.request_context.lifespan_context`
2. Calls `init_repository_node(adapter, InitRepositoryNodeArgs(graph_id="owner/name"))`
3. The tool module calls `adapter.get_repo_info(graph_id="owner/name")` which runs:

```cypher
MATCH (r:Repository {graph_id: $gid})
OPTIONAL MATCH (f:File {graph_id: $gid}) WHERE f.deleted = false
OPTIONAL MATCH (fn:Function {graph_id: $gid})
RETURN r.graph_id AS graph_id, ..., count(DISTINCT f) AS file_count, count(DISTINCT fn) AS function_count
```

4. Returns `{"file_count": 42, "function_count": 180, ...}`
5. Server wraps in `CallToolResult(content=[TextContent("Repository 'owner/name': 42 files, 180 functions")], structuredContent={...})`

**Data flow:**
```
LLM → tools/call → FastMCP → @mcp.tool() → tool module → adapter.get_repo_info()
  → Bolt → Neo4j → MATCH (r:Repository {graph_id: $gid}) OPTIONAL MATCH ...
  → results → tool module → InitRepositoryNodeResult model
  → CallToolResult(TextContent + structuredContent) → stdout → Claude → LLM
```

---

## Step 6: The LLM calls `find_file_dependencies` (the flagship)

Now the LLM calls the tool that answers your question:

```json
{"jsonrpc": "2.0", "id": 4, "method": "tools/call",
 "params": {"name": "find_file_dependencies",
            "arguments": {"graph_id": "owner/name",
                           "file_path": "auth_service.py",
                           "direction": "both",
                           "max_hops": 2}}}
```

The server's `@mcp.tool()` function calls the tool module, which calls
`adapter.find_file_dependencies(graph_id="owner/name", file_path="auth_service.py", ...)`.

The adapter runs **5 parameterized Cypher queries** against Neo4j, all filtered on
`graph_id = $gid`:

### Query 1: `imported_by` — who imports this file?
```cypher
MATCH (src:File {graph_id: $gid})-[:IMPORTS]->(tgt:File {graph_id: $gid, path: $p})
WHERE src.deleted = false
RETURN src.path AS path, 'file' AS kind, 'imported_by' AS via, 1 AS hop
```
→ Returns files that would break if `auth_service.py` changes.

### Query 2: `imports` — what does this file import?
```cypher
MATCH (src:File {graph_id: $gid, path: $p})-[:IMPORTS]->(tgt:File {graph_id: $gid})
WHERE tgt.deleted = false
RETURN tgt.path AS path, 'file' AS kind, 'imports' AS via, 1 AS hop
```
→ Returns files `auth_service.py` depends on (changes here could also break it).

### Query 3: `callers` — who calls functions defined in this file?
```cypher
MATCH (caller:Function {graph_id: $gid})-[:CALLS]->(callee:Function {graph_id: $gid})
<-[:DEFINES]-(calleeFile:File {graph_id: $gid, path: $p})
RETURN caller.qualified_name AS path, 'function' AS kind, 'called_by' AS via, 1 AS hop
```
→ Returns functions in other files that call functions defined in `auth_service.py`.
This traverses the `DEFINES` edge (language-agnostic — works for both Python and JS/TS).

### Query 4: `calls` — what functions does this file call?
```cypher
MATCH (callerFile:File {graph_id: $gid, path: $p})-[:DEFINES]->(caller:Function {graph_id: $gid})
-[:CALLS]->(callee:Function {graph_id: $gid})
RETURN callee.qualified_name AS path, 'function' AS kind, 'calls' AS via, 1 AS hop
```
→ Returns functions `auth_service.py`'s functions call.

### Query 5: `external_symbols` — unresolved dependencies (stdlib/npm)
```cypher
MATCH (f:File {graph_id: $gid, path: $p})-[:IMPORTS]->(s:Symbol {graph_id: $gid})
RETURN s.name AS name, s.kind AS kind
```
Plus a second query for unresolved calls from Function nodes through CALLS to Symbol.
→ Returns external packages like `os`, `react`, `jsonwebtoken` — things the repo
depends on that aren't in the graph.

**Data flow:**
```
LLM → tools/call → FastMCP → @mcp.tool() → tool module → adapter.find_file_dependencies()
  → 5× Bolt queries → Neo4j traverses IMPORTS + CALLS + DEFINES edges
  → 5 result sets → merged into one dict → FindFileDependenciesResult model
  → CallToolResult(TextContent summary + structuredContent) → stdout → Claude → LLM
```

---

## Step 7: The LLM reasons and answers

Claude receives the `CallToolResult`:
- **TextContent** (human-readable summary): `"Dependencies for 'auth_service.py' in 'owner/name':\n  Imported by (3): ..."`
- **structuredContent** (machine-readable): `{"file": {...}, "imported_by": [...], "imports": [...], "callers": [...], ...}`

The LLM reads both, reasons over the subgraph, and formulates an answer:

> "Modifying `auth_service.py` could break 3 files that import it:
> `user_service.py`, `api_routes.py`, and `middleware/auth.py`.
> Additionally, 2 functions in other files call `authenticate()` and
> `verify_token()` defined in `auth_service.py`. The file also depends on
> external packages `os`, `hashlib`, and `jwt` — changes to how those are
> used could also cause issues."

**Data flow:**
```
JSON-RPC response (stdout) → Claude Desktop → LLM context window
  → LLM reasons over subgraph → natural-language answer → your screen
```

---

## Full Data Flow Diagram

```
GitHub repo (.py / .ts / .js files)
    │
    │  `codegraph ingest <url>`
    ▼
┌─────────────── INGESTION (offline CLI) ────────────────┐
│  git clone --depth 1                                    │
│  walker.py → file tree (respects .gitignore)           │
│  python_parser.py → ast → functions/classes/imports    │
│  jsts_parser.py → tree-sitter → functions/imports      │
│  commits.py → one git log pass → per-file metadata     │
│  graph_builder.py → Cypher MERGE plan (parameterized)  │
│  adapter._run_write() → Bolt → Neo4j                  │
└────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────── NEO4J (docker-compose, bolt://localhost:7687) ───┐
│  (:Repository)-[:CONTAINS]->(:File)-[:DEFINES]->(:Function)     │
│  (:File)-[:IMPORTS]->(:File | :Symbol)                          │
│  (:Function)-[:CALLS]->(:Function | :Symbol)                   │
│  All nodes carry graph_id for multi-repo isolation              │
└─────────────────────────────────────────────────────────────────┘
    │
    │  `codegraph serve` (spawned by MCP host)
    ▼
┌─────────────── MCP SERVER (stdio) ────────────────────┐
│  FastMCP v1.x                                         │
│  lifespan: connect + apply_migrations                 │
│  6 @mcp.tool() → adapter → Cypher → Neo4j → results  │
│  2 @mcp.resource() → adapter → Cypher → JSON         │
│  All Cypher parameterized, all filter on graph_id     │
│  stdout = JSON-RPC only, stderr = logging             │
└──────────────────────────────────────────────────────┘
    │
    │  JSON-RPC over stdin/stdout
    ▼
┌─────────────── MCP HOST (Claude Desktop / opencode / Cursor) ──┐
│  Spawns server as subprocess                                    │
│  initialize → tools/list → tools/call → reads response          │
│  LLM reasons over returned subgraph                             │
└────────────────────────────────────────────────────────────────┘
    │
    ▼
  Developer's answer on screen
```

---

## Key Design Decisions Visible in the Flow

1. **Process split:** Ingestion is a separate CLI process that exits. The server
   never clones, parses, or writes — it only reads. This keeps the server fast and
   sandboxed.

2. **`graph_id` isolation:** Every Cypher statement filters `WHERE n.graph_id = $gid`.
   The LLM passes `graph_id` as a parameter but can never read across repos — this is
   enforced server-side, not by client trust.

3. **`Symbol` leaf nodes:** Unresolved imports (stdlib, npm) become `:Symbol` nodes,
   not phantom `:File` nodes. The graph records that the dependency exists without
   inventing fake files. This is why `find_file_dependencies` returns a separate
   `external_symbols` list.

4. **Parameterized Cypher everywhere:** No string-formatted values. The Neo4j driver's
   `execute_query(cypher, **params)` handles parameter binding — this prevents Cypher
   injection and is the official driver pattern.

5. **Two-pass CALLS resolution during ingestion:** A file's `funcA` may call `funcB`
   defined later in the same file or in a file parsed after this one. So calls are
   accumulated in-process and only MERGED into Neo4j after all `:Function` nodes exist.

6. **File-scoped qualified_names for JS/TS:** `path::funcname` prevents two files
   each defining `function authenticate` from colliding into one Function node. Python
   uses dotted qnames (`Class.method`) since Python's module system prevents this.

7. **Soft-delete tombstones:** Re-ingesting a repo MERGEs changed nodes and sets
   `deleted=true` on files no longer in the working tree — never hard-deletes. Only
   `codegraph reset --graph-id X` (CLI, destructive) hard-wipes.
