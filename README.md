# codegraph-mcp

**A knowledge graph of your code, served to any LLM over the Model Context Protocol.**

`codegraph-mcp` clones a Git repository, parses it into a Neo4j dependency graph
(`Repository` → `File` → `Function`, linked by `CONTAINS` / `DEFINES` / `IMPORTS` /
`CALLS`), and exposes that graph as read-only MCP tools. An agent can then answer
*"what breaks if I change `auth_service.py`?"* by traversing edges — one structured
query instead of re-reading the repo into its context window every session.

It ships with a browser UI that renders the same graph as a layered architecture
map, so the graph is useful to you as well as to the model.

---

## Contents

- [How it works](#how-it-works) · [Quick start](#quick-start) · [Ingest a repo](#ingest-a-repo)
- [Connect an MCP host](#connect-an-mcp-host) · [MCP tools](#mcp-tools) · [CLI](#cli)
- [Web UI](#web-ui-codegraph-viz) · [Private repositories](#private-repositories)
- [Configuration](#configuration) · [Troubleshooting](#troubleshooting)

---

## How it works

Three phases, deliberately split across two processes:

| Phase | Process | What it does |
|---|---|---|
| **1. Ingest** | `codegraph ingest` (offline CLI) | Shallow-clones the repo, walks it honoring `.gitignore`, parses each file, and writes nodes + edges to Neo4j. One `git log` pass records per-file commit metadata. |
| **2. Serve** | `codegraph serve` (MCP stdio server) | Answers tool calls with parameterized Cypher. Never clones, never writes, holds no state between calls. |
| **3. Consume** | Your MCP host | Claude Desktop, Cursor, opencode, or any MCP client spawns the server as a subprocess. |

**Why the split.** All the slow, risky work (network, disk, parsing) lives in the
offline phase, so the server stays sandboxed and fast — no clone timeouts, no
write path to abuse.

**Repo isolation.** Every node and edge carries a `graph_id`, and every Cypher
statement filters on it. Many repos share one database with no cross-talk, and
it's a server-side guarantee rather than client trust. The `graph_id` is
host-qualified (`github.com/owner/name`), so the same `owner/name` on GitHub and
on an internal GitLab stay separate graphs.

**An honest graph.** Imports that resolve outside the repo (stdlib, npm packages)
become lightweight `Symbol` leaves instead of phantom files. Re-ingestion is
idempotent — nodes are upserted with `MERGE`, and files deleted from the tree are
tombstoned rather than hard-deleted.

**Languages.** Python (stdlib `ast`); JavaScript, TypeScript, TSX/JSX, Java, and
Kotlin (tree-sitter). Adding one more means adding a row to
`src/codegraph/ingestion/languages.py` plus a parser and an import resolver.

---

## Quick start

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and Docker.

```bash
git clone <codegraph-mcp> && cd codegraph-mcp
uv sync --extra dev          # all deps pinned via uv.lock
cp .env.example .env
docker compose up -d         # Neo4j on bolt://localhost:7687
uv run pytest -m "not slow and not integration"
```

## Ingest a repo

```bash
uv run codegraph ingest https://github.com/<owner>/<name>
# → {"graph_id": "github.com/owner/name", "files": 142, "functions": 880, ...}

uv run codegraph ls          # what's in the graph so far
```

## Connect an MCP host

Point the host at the project directory; it spawns the server over stdio.

<details open>
<summary><b>Claude Desktop</b> — <code>claude_desktop_config.json</code></summary>

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
</details>

<details>
<summary><b>Cursor</b> — <code>~/.cursor/mcp.json</code></summary>

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
</details>

<details>
<summary><b>opencode</b> — <code>opencode.json</code></summary>

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
</details>

No host handy? Drive it with the MCP Inspector:

```bash
uv run mcp dev src/codegraph/server.py
```

## MCP tools

All tools are read-only and scoped by `graph_id`.

| Tool | Answers |
|---|---|
| `list_repos` | Which repos are ingested? |
| `init_repository_node` | Does this repo's graph exist, and how big is it? |
| `get_repo_structure` | What's the tree under this path? |
| **`find_file_dependencies`** | **What depends on this file, or does it depend on — in either direction, up to N hops?** |
| `search_nodes` | Which functions or files match this name? |
| `get_node_detail` | What is this node — kind, line range, parent? |
| `get_file_content` | The real source text of a file (optional line range). |
| `get_function_source` | The source body of one function, by node id. |
| `get_file_metadata` | Who last touched this file, when, and in which commit? |

Two resources ground the model at session start: `codegraph://repos` (everything
ingested) and `codegraph://schema/{graph_id}` (label and edge breakdown for one repo).

Errors are written for an LLM to recover from: bad arguments surface as JSON-RPC
`-32602`, and business errors (unknown repo, missing file) return `isError: true`
with plain-text guidance on what to try next.

## CLI

| Command | Purpose |
|---|---|
| `codegraph ingest <url> [--branch B] [--force]` | Clone, parse, and load a repo into Neo4j |
| `codegraph ls` | List ingested repos |
| `codegraph serve` | Run the MCP server (stdio) — normally spawned by the host |
| `codegraph viz [--host H] [--port P]` | Run the local web UI |
| `codegraph reset --graph-id <id> [--keep-clone]` | Hard-wipe one repo (destructive; also removes the clone unless `--keep-clone`) |

A `Makefile` wraps the common loops: `make dev`, `make up`, `make test`,
`make lint`, `make typecheck`, `make viz`.

## Web UI (`codegraph viz`)

A read-only browser view of the same graph the MCP tools query. It runs as its
own process, so the MCP server's stdout stays pure JSON-RPC.

```bash
make up                                            # Neo4j
uv run codegraph ingest https://github.com/owner/name
make viz-build                                     # one-time, needs Node 18+
make viz                                           # → http://127.0.0.1:8787
```

Skip `viz-build` and the API still serves — `/` just returns a hint to build the
frontend.

**The layout carries meaning.** The default view is an architecture map, not a
force-directed hairball: a node's row is its dependency depth (entry points on
top, leaves at the bottom) and its size is how many files depend on it. Within a
row, nodes are ordered to minimise edge crossings — a barycenter sweep plus a
transpose refinement, as in Sugiyama layered drawing — which measured 60% fewer
crossings than ordering rows by path.

**The Findings panel** answers the questions you actually ask of an unfamiliar
codebase. Each finding is clickable and highlights on the canvas.

| Finding | Question it answers |
|---|---|
| **Hubs** | What is the spine of this system, and what is riskiest to change? |
| **Entry points** | Where do I start reading? |
| **Orphans** | What is dead, or reached some way the imports don't show? |
| **Cycles** | Where is it tangled? (members share a row; the level edge is dashed red) |
| **Change coupling** | What keeps changing together — especially pairs with *no* import between them, which is coupling the code never admits to |
| **Risk** | Commits × dependents: changed often *and* widely depended on. The **Risk overlay** paints the canvas with this as a sequential ramp |

Plus search, click-to-highlight a neighbourhood (outgoing blue, incoming orange),
particle flow along a hovered file's edges, a minimap, a detail panel with source
and per-file imports/dependents/functions, and blast radius for a change. Change
coupling reads the on-disk clone's git log; everything else is graph structure.

**Development** (hot reload) is two processes:

```bash
make viz-dev                 # terminal 1 — API on :8787
cd vizui && npm run dev      # terminal 2 — Vite on :5173, proxies /api
```

## Private repositories

Cloning a private repo needs credentials. In order of preference:

**1. SSH keys or your OS credential helper** — nothing to configure. Ingestion
shells out to `git`, which inherits your environment: if `git clone` works in
your terminal it works here. Use an SSH URL (`git@github.com:owner/name.git`) or
let the credential manager answer.

**2. `GIT_TOKEN`** — for headless/CI, where no ambient credentials exist:

```bash
GIT_TOKEN=<personal-access-token> uv run codegraph ingest https://github.com/owner/private
```

The token is injected only for the duration of the network call; `origin` is
immediately rewritten to a credential-free URL, so nothing is left in
`.git/config`. The URL stored in Neo4j and every failure message are sanitized,
so a token never reaches the graph or your logs.

> [!IMPORTANT]
> Two limits worth knowing:
> - The authenticated URL is passed to the `git` subprocess, so on a **shared
>   machine** another user could see it via `ps` while a clone runs. On a
>   single-user machine this is a non-issue; if it matters, use SSH.
> - With `GIT_TOKEN` set and `GIT_TOKEN_HOST` unset, the token is sent to
>   **whatever https host you clone**. If you use more than one git host, set
>   `GIT_TOKEN_HOST=github.com`.

## Configuration

Copy `.env.example` to `.env`. Every value has a working default.

| Variable | Default | Purpose |
|---|---|---|
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` / `NEO4J_DB` | `bolt://localhost:7687`, `neo4j`, … | Graph database connection |
| `REPOS_DIR` | `./repos` | Where clones are cached and source is read from |
| `INGEST_DEPTH` | `1` | Clone depth (`1` = shallow) |
| `INGEST_BATCH_SIZE` | `200` | Rows per Cypher write batch |
| `MAX_DEPENDENCY_RESULTS` | `500` | Cap on `find_file_dependencies` results |
| `GIT_TOKEN` / `GIT_TOKEN_HOST` / `GIT_TOKEN_USERNAME` | unset | Headless auth — see [Private repositories](#private-repositories) |
| `VIZ_HOST` / `VIZ_PORT` | `127.0.0.1` / `8787` | Web UI bind address. Loopback by default, since it serves a whole repo's source |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Troubleshooting

**`uv run` fails with `failed to remove file ... codegraph.exe ... used by another process`.**
A running `codegraph serve` (spawned by your MCP host) is holding the entry
point while `uv` tries to replace it after a dependency change. Either skip the
reinstall:

```bash
uv run --no-sync codegraph viz
```

…or fix it once: stop the MCP server (on Windows, `tasklist | findstr codegraph`
then `Stop-Process -Id <pid>`), run `uv sync --extra dev`, and let the host
respawn it.

## Tech stack

Python 3.11+, `mcp>=1.27,<2` (FastMCP), Neo4j 5.x, pydantic v2, tree-sitter,
GitPython, uv — with pytest, ruff, and mypy on the dev side. The web UI adds
FastAPI + uvicorn on the backend and Vite + React + Cytoscape.js on the frontend.

## Project status

**v0.1** — stdio transport, Neo4j 5.x backend, nine read-only tools, six
languages.

## Further reading

- **[CONTRIBUTING.md](CONTRIBUTING.md)** — architecture, hard conventions, testing strategy, CI gates
- **[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)** — the problem, the design, and why it's shaped this way
- **[docs/data-flow-explainer.md](docs/data-flow-explainer.md)** — how a request travels through the system

## License

MIT.
