# codegraph-mcp

Knowledge-Graph MCP Server for GitHub repos. Ingests any GitHub repo's code into a
Neo4j graph (Repository / File / Function nodes; CONTAINS / DEFINES / IMPORTS / CALLS
edges) and exposes that graph as read-only MCP tools to any MCP host — Claude Desktop,
opencode, Cursor, or any client that speaks the Model Context Protocol.

## Status

v0.1 — stdio transport, Neo4j 5.x backend. Parses Python (stdlib `ast`) and
JS/TS/TSX, Java, and Kotlin (tree-sitter).

## Quick start

```bash
git clone <codegraph-mcp> && cd codegraph-mcp
uv sync --extra dev              # all deps pinned via uv.lock
docker compose up -d             # Neo4j on bolt://localhost:7687
cp .env.example .env
uv run pytest -m "not slow and not integration"
```

## Ingest a repo

```bash
uv run codegraph ingest https://github.com/<owner>/<name>
# → {"graph_id": "owner/name", "files": 142, "functions": 880, ...}
```

## Private repositories

Cloning a private repo needs credentials. In order of preference:

1. **SSH keys or your OS credential helper** — nothing to configure here. The
   ingest CLI shells out to `git`, which inherits your environment, so if
   `git clone` works in your terminal it works here. Use an SSH URL
   (`git@github.com:owner/name.git`) or let the credential manager answer.
2. **`GIT_TOKEN`** — for headless/CI, where no ambient credentials exist:

   ```bash
   GIT_TOKEN=<personal-access-token> uv run codegraph ingest https://github.com/owner/private
   ```

**How the token is handled.** It is injected only for the duration of the
network call, then `origin` is immediately rewritten to a credential-free URL,
so nothing is left in `.git/config`. The URL stored in Neo4j and every message
printed on failure are sanitized, so a token never reaches the graph or your
logs.

**Two limits worth knowing:**

- The authenticated URL is passed to the `git` subprocess, so on a **shared
  machine** another user could see it via `ps` while a clone runs. On a
  single-user machine this is a non-issue; if it matters to you, use SSH.
- With `GIT_TOKEN` set and `GIT_TOKEN_HOST` unset, the token is sent to
  **whatever https host you clone**. If you use more than one git host, set
  `GIT_TOKEN_HOST=github.com` so a token for one host is never offered to
  another.

`graph_id` is host-qualified (`github.com/owner/name`), so the same
`owner/name` on GitHub and on an internal GitLab stay separate graphs.

## Connect an MCP host

### Claude Desktop (`claude_desktop_config.json`)

```jsonc
{
  "mcpServers": {
    "codegraph": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\path\\to\\codegraph-mcp", "codegraph", "serve"]
    }
  }
}
```

### opencode (in `opencode.json`)

```jsonc
{
  "mcp": {
    "codegraph": {
      "type": "local",
      "command": ["uv", "run", "--directory", "/path/to/codegraph-mcp", "codegraph", "serve"]
    }
  }
}
```

### Cursor (`~/.cursor/mcp.json`)

```jsonc
{
  "mcpServers": {
    "codegraph": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/codegraph-mcp", "codegraph", "serve"]
    }
  }
}
```

### MCP Inspector (for testing without an MCP host)

```bash
uv run mcp dev src/codegraph/server.py
```

## CLI

| Command | Purpose |
|---|---|
| `codegraph ingest <url> [--branch main] [--force]` | Clone + parse + load a repo into Neo4j |
| `codegraph serve` | Run the MCP server (stdio) — spawned by the MCP host |
| `codegraph reset --graph-id <owner/name>` | Hard-wipe one repo from Neo4j (destructive) |
| `codegraph ls` | List ingested repos |
| `codegraph viz [--host H] [--port P]` | Run the local web UI (browser graph viewer) |

## Tools

| Tool | Purpose |
|---|---|
| `list_repos` | List ingested repos |
| `init_repository_node` | Confirm a repo's graph exists; return file/function counts |
| `get_repo_structure` | Tiered tree view under a path |
| `find_file_dependencies` | **Flagship:** what files/funcs depend on (or are depended on by) a file |
| `search_nodes` | Find functions/files by name |
| `get_node_detail` | Deep detail on one node (line range, kind) |
| `get_file_content` | Return real source text for a file (optional line range) |
| `get_function_source` | Return one function's source body by node id |

## Local web UI (`codegraph viz`)

A read-only browser view of the same graph the MCP tools query — files and
directories as nodes, imports as directional arrows, pan/zoom, search, and a
blast-radius panel. It is a separate process from `codegraph serve`; the MCP
server's stdout stays pure JSON-RPC.

```bash
make up                 # Neo4j
codegraph ingest https://github.com/owner/name
make viz-build          # one-time: builds vizui/dist (needs Node 18+)
make viz                # → http://127.0.0.1:8787
```

Without `make viz-build` the API still serves, and `/` returns a hint telling
you to build the frontend.

**What you get:** an overview of directory clusters (click one to expand a
level), zoom-gated labels, click-to-highlight of a file's neighborhood
(outgoing blue, incoming red), particle flow along a hovered file's edges, a
minimap, a detail panel with source and per-file imports/dependents/functions,
and an Impact button for the transitive blast radius of a change.

**Development** (hot reload) is two processes:

```bash
make viz-dev                    # terminal 1 — API on :8787
cd vizui && npm run dev         # terminal 2 — Vite on :5173, proxies /api
```

Configure the bind address with `VIZ_HOST` / `VIZ_PORT` (defaults
`127.0.0.1:8787` — loopback, since this serves a whole repo's source).

## Tech stack

Python 3.11+, `mcp>=1.27,<2` (stable v1.x FastMCP), Neo4j 5.x, pydantic v2, tree-sitter, GitPython, pytest, ruff, mypy, uv. The web UI adds FastAPI + uvicorn on the backend and Vite + React + Cytoscape.js on the frontend.

See `CONTRIBUTING.md` for architecture, conventions, and testing strategy.
