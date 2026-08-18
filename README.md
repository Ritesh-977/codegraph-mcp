# codegraph-mcp

Knowledge-Graph MCP Server for GitHub repos. Ingests any GitHub repo's code into a
Neo4j graph (Repository / File / Function nodes; CONTAINS / DEFINES / IMPORTS / CALLS
edges) and exposes that graph as read-only MCP tools to any MCP host — Claude Desktop,
opencode, Cursor, or any client that speaks the Model Context Protocol.

## Status

v0.1 — stdio transport, Neo4j 5.x backend, Python `ast` + tree-sitter (JS/TS/TSX) parsing.

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

## Tools

| Tool | Purpose |
|---|---|
| `list_repos` | List ingested repos |
| `init_repository_node` | Confirm a repo's graph exists; return file/function counts |
| `get_repo_structure` | Tiered tree view under a path |
| `find_file_dependencies` | **Flagship:** what files/funcs depend on (or are depended on by) a file |
| `search_nodes` | Find functions/files by name |
| `get_node_detail` | Deep detail on one node (line range, kind) |

## Tech stack

Python 3.11+, `mcp>=1.27,<2` (stable v1.x FastMCP), Neo4j 5.x, pydantic v2, tree-sitter, GitPython, pytest, ruff, mypy, uv.

See `CONTRIBUTING.md` for architecture, conventions, and testing strategy.
