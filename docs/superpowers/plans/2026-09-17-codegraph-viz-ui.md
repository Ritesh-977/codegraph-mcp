# codegraph-viz Interactive Codebase Relationship Browser — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `codegraph viz` — a local web app that renders the Neo4j code graph (files, dirs, dependencies, flow arrows) as an interactive, zoomable, searchable canvas, plus directory clusters, minimap, neighborhood highlight, blast-radius impact view, and a file detail panel with source.

**Architecture:** A new `src/codegraph/viz/` backend package (FastAPI + a `VizService` query layer over the existing `Neo4jAdapter`) exposes REST endpoints. A new Vite+React+Cytoscape.js frontend at `vizui/` renders the graph; FastAPI serves the production build and the Vite dev server proxies `/api` during development. The MCP stdio server is untouched; `codegraph viz` is a separate process.

**Status:** Implemented on branch `feat/codegraph-viz` (13 tasks, 13 commits). Deviations found during execution are recorded in "Execution notes" at the end.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, pydantic v2; CSS-free dark React 18 + TypeScript + Vite 5 + Cytoscape.js + cytoscape-fcose; Vitest for pure frontend mapping tests.

## Global Constraints

- **Every Cypher query MUST be parameterized and contain a `WHERE ... graph_id = $gid` (or equivalent) predicate.** The only literal interpolation allowed is a pre-validated hop bound in `[:IMPORTS*1..{d}]` (Neo4j cannot parameterize variable-length bounds) — validate the bound exactly like `_validated_hop_bound` in `src/codegraph/repo/neo4j_adapter.py:27-45`.
- **Read-only.** `codegraph viz` never writes to Neo4j. No `_run_write`, no `soft_cleanup`.
- **`codegraph serve` (MCP stdio) stays byte-identical.** `stdout` of the MCP server remains pure JSON-RPC. `viz` is a separate process writing logs to stderr only.
- **stdout/stderr rule for viz:** FastAPI/uvicorn logs go to stderr; never `print()` to stdout in the web process.
- **API errors are LLM/UI-readable:** JSON `{"detail": <message>, "hint": <what to do next>}` everywhere. No stack traces surfaced.
- **`graph_id` isolation:** every query scope-filtered to one repo slug; users pick a repo at a time.
- **File paths are repo-relative POSIX** (forward slashes).
- **Tests run offline** on fixtures / fake adapters; Neo4j-backed tests use the existing testcontainers harness in `tests/integration/conftest.py` (fresh `graph_id` per test) and are marked `integration`.
- `uv run` is the command runner. `make lint typecheck test` must stay green (ruff + mypy strict on `src/`, pytest non-integration default).
- New runtime deps `fastapi>=0.115,<1` and `uvicorn>=0.30,<1` are added to `pyproject.toml` `dependencies` (not dev) — the web app is part of the product.

---

### Task 1: Runtime deps, Settings, and .env.example

**Files:**
- Modify: `pyproject.toml:11-26` (add 2 lines to `dependencies`)
- Modify: `src/codegraph/config.py:20-24` (add 2 fields)
- Modify: `.env.example` (append 2 lines)
- Test: `tests/unit/test_viz_settings.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings.viz_host: str` (default `"127.0.0.1"`), `Settings.viz_port: int` (default `8787`); runtime deps `fastapi`, `uvicorn` available to import.

- [x] **Step 1: Write the failing test**

Create `tests/unit/test_viz_settings.py`:

```python
"""codegraph-viz settings surface."""

from __future__ import annotations

from codegraph.config import Settings


def test_viz_defaults() -> None:
    s = Settings()
    assert s.viz_host == "127.0.0.1"
    assert s.viz_port == 8787


def test_viz_overridable_via_env(monkeypatch) -> None:
    monkeypatch.setenv("VIZ_HOST", "0.0.0.0")
    monkeypatch.setenv("VIZ_PORT", "9090")
    s = Settings()
    assert s.viz_host == "0.0.0.0"
    assert s.viz_port == 9090
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_viz_settings.py -v`
Expected: FAIL — `Settings` has no attribute `viz_host` / default mismatch.

- [x] **Step 3: Add dependencies**

In `pyproject.toml` `[project] dependencies`, append (keep alphabetical-ish/grouped):

```toml
    "fastapi>=0.115,<1",
    "uvicorn>=0.30,<1",
```

Run `uv sync --extra dev` to install them.

- [x] **Step 4: Add Settings fields**

Append to the end of `src/codegraph/config.py` (after `log_level`):

```python
    # Local web UI (`codegraph viz`). Host/port bound by uvicorn.
    viz_host: str = "127.0.0.1"
    viz_port: int = 8787
```

- [x] **Step 5: Update .env.example**

Append:

```
# Local web UI (`codegraph viz`)
VIZ_HOST=127.0.0.1
VIZ_PORT=8787
```

- [x] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_viz_settings.py -v`
Expected: PASS (2 passed).

- [x] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/codegraph/config.py .env.example tests/unit/test_viz_settings.py
git commit -m "feat(viz): add fastapi/uvicorn deps + VIZ_HOST/VIZ_PORT settings"
```

---

### Task 2: UI wire-format pydantic models

**Files:**
- Create: `src/codegraph/viz/__init__.py`
- Create: `src/codegraph/viz/models.py`
- Test: `tests/unit/test_viz_models.py` (create)

**Interfaces:**
- Consumes: `MAX_TRAVERSAL_HOPS` from `src/codegraph/models/common.py`.
- Produces: `GraphNode`, `GraphEdge`, `GraphStats`, `GraphPayload`, `SubgraphRequest`, `ImpactRequest`, `ImpactRing`, `ImpactPayload`, `ExpandResult`, `FunctionInfo`, `FileDetailResponse` — exact shapes below.

- [x] **Step 1: Write the failing test**

Create `tests/unit/test_viz_models.py`:

```python
"""Wire-format model validation for codegraph-viz."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from codegraph.models.common import MAX_TRAVERSAL_HOPS
from codegraph.viz.models import (
    GraphPayload,
    ImpactRequest,
    SubgraphRequest,
)


def test_subgraph_requires_valid_direction() -> None:
    with pytest.raises(ValidationError):
        SubgraphRequest(graph_id="o/n", seed_path="a.py", direction="sideways")


def test_subgraph_depth_bounds() -> None:
    with pytest.raises(ValidationError):
        SubgraphRequest(graph_id="o/n", seed_path="a.py", depth=0)
    with pytest.raises(ValidationError):
        SubgraphRequest(graph_id="o/n", seed_path="a.py", depth=MAX_TRAVERSAL_HOPS + 1)
    ok = SubgraphRequest(graph_id="o/n", seed_path="a.py", depth=2)
    assert ok.direction == "both"
    assert ok.include_symbols is True


def test_impact_max_hops_bounds() -> None:
    with pytest.raises(ValidationError):
        ImpactRequest(graph_id="o/n", seed_path="a.py", max_hops=0)
    ok = ImpactRequest(graph_id="o/n", seed_path="a.py", max_hops=1)
    assert ok.max_hops == 1


def test_graph_payload_roundtrip() -> None:
    payload = GraphPayload.model_validate({
        "graph_id": "o/n",
        "view": "full",
        "nodes": [{"id": "file:a.py", "kind": "file", "label": "a.py", "path": "a.py", "language": "python"}],
        "edges": [{"source": "file:a.py", "target": "sym:os", "type": "IMPORTS"}],
        "stats": {"file_count": 1, "edge_count": 1, "truncated": False, "view": "full"},
    })
    assert payload.nodes[0].path == "a.py"
    assert payload.edges[0].type == "IMPORTS"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_viz_models.py -v`
Expected: FAIL — `ModuleNotFoundError: codegraph.viz.models`.

- [x] **Step 3: Create the viz package and models**

Create `src/codegraph/viz/__init__.py`:

```python
"""codegraph-viz — local web UI over the codegraph Neo4j graph."""
```

Create `src/codegraph/viz/models.py`:

```python
"""UI wire-format models for codegraph-viz.

Independent of the MCP/DTO models in ``codegraph.models``: this is the
contract between the FastAPI layer and the React frontend.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from codegraph.models.common import MAX_TRAVERSAL_HOPS


class GraphNode(BaseModel):
    id: str
    kind: Literal["file", "dir_cluster", "symbol", "function"]
    label: str
    path: str | None = None
    language: str | None = None
    file_count: int | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    type: Literal["IMPORTS", "CALLS", "DEFINES"]
    weight: int = 1


class GraphStats(BaseModel):
    file_count: int
    edge_count: int
    truncated: bool = False
    view: str


class GraphPayload(BaseModel):
    graph_id: str
    view: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stats: GraphStats


class SubgraphRequest(BaseModel):
    graph_id: str
    seed_path: str
    direction: Literal["imports", "imported_by", "both"] = "both"
    depth: int = Field(default=2, ge=1, le=MAX_TRAVERSAL_HOPS)
    include_symbols: bool = True


class ImpactRequest(BaseModel):
    graph_id: str
    seed_path: str
    max_hops: int = Field(default=2, ge=1, le=MAX_TRAVERSAL_HOPS)


class ImpactRing(BaseModel):
    hop: int
    paths: list[str]


class ImpactPayload(BaseModel):
    graph_id: str
    seed_path: str
    rings: list[ImpactRing]
    callers: list[str] = []
    calls: list[str] = []
    truncated: bool = False


class ExpandResult(BaseModel):
    """Immediate children of a directory: files plus edges among and to them."""

    graph_id: str
    dir_prefix: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class FunctionInfo(BaseModel):
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int


class FileDetailResponse(BaseModel):
    graph_id: str
    path: str
    language: str | None = None
    last_author: str | None = None
    last_commit_at: str | None = None
    last_commit_sha: str | None = None
    content: str
    start_line: int
    end_line: int
    truncated: bool = False
    functions: list[FunctionInfo] = []
    imported_by: list[str] = []
    imports: list[str] = []
    external_symbols: list[str] = []
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_viz_models.py -v`
Expected: PASS (4 passed).

- [x] **Step 5: Commit**

```bash
git add src/codegraph/viz tests/unit/test_viz_models.py
git commit -m "feat(viz): wire-format pydantic models"
```

---

### Task 3: Directory clustering (pure functions)

**Files:**
- Create: `src/codegraph/viz/clustering.py`
- Test: `tests/unit/test_viz_clustering.py` (create)

**Interfaces:**
- Consumes: `GraphNode`, `GraphEdge` from `viz/models.py` (Task 2).
- Produces: `cluster_key(path: str, depth: int) -> str | None` and
  `build_cluster_graph(nodes, edges, depth) -> tuple[list[GraphNode], list[GraphEdge]]`.

- [x] **Step 1: Write the failing test**

Create `tests/unit/test_viz_clustering.py`:

```python
"""Pure directory-clustering for the overview view."""

from __future__ import annotations

from codegraph.viz.clustering import build_cluster_graph, cluster_key
from codegraph.viz.models import GraphEdge, GraphNode


def _node(nid: str, path: str) -> GraphNode:
    return GraphNode(id=nid, kind="file", label=path.rsplit("/", 1)[-1], path=path)


def test_cluster_key_depth1() -> None:
    assert cluster_key("a.py", 1) is None            # root file stays file node
    assert cluster_key("src/a.py", 1) == "src"
    assert cluster_key("src/deep/a.py", 1) == "src"
    assert cluster_key("src/deep/a.py", 2) == "src/deep"


def test_build_cluster_graph_groups_and_aggregates() -> None:
    nodes = [
        _node("f:a.py", "a.py"),
        _node("f:src/a1.py", "src/a1.py"),
        _node("f:src/a2.py", "src/a2.py"),
        _node("f:lib/u.py", "lib/u.py"),
    ]
    edges = [
        GraphEdge(source="f:a.py", target="f:src/a1.py", type="IMPORTS"),
        GraphEdge(source="f:src/a1.py", target="f:src/a2.py", type="IMPORTS"),
        GraphEdge(source="f:src/a1.py", target="f:a.py", type="IMPORTS"),
        GraphEdge(source="f:src/a2.py", target="f:lib/u.py", type="IMPORTS"),
    ]
    cn, ce = build_cluster_graph(nodes, edges, depth=1)
    kinds = {n.kind for n in cn}
    assert "dir_cluster" in kinds and "file" in kinds
    # a.py stays a file node
    assert any(n.id == "f:a.py" for n in cn)
    # dirs become clusters with counts
    src = next(n for n in cn if n.id == "dir:src")
    lib = next(n for n in cn if n.id == "dir:lib")
    assert src.file_count == 2
    assert lib.file_count == 1
    # aggregated edge weights
    agg = {(e.source, e.target): e.weight for e in ce}
    assert agg[("f:a.py", "dir:src")] == 1
    # two distinct src files import/export: src/a1 -> a2 is an internal edge,
    # dropped as a self-loop; src->a.py counts once
    assert agg[("dir:src", "f:a.py")] == 1
    assert agg[("dir:src", "dir:lib")] == 1
    # deterministic ordering
    assert [n.id for n in cn] == sorted(n.id for n in cn)
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_viz_clustering.py -v`
Expected: FAIL — `ModuleNotFoundError: codegraph.viz.clustering`.

- [x] **Step 3: Implement clustering.py**

Create `src/codegraph/viz/clustering.py`:

```python
"""Pure file -> directory-cluster aggregation for the overview view.

Keeps the logic free of I/O so it is trivially unit-testable. Files whose
path is shallower than ``depth`` remain file nodes; deeper files are grouped
under their ``depth``-segment directory prefix as ``dir_cluster`` nodes.
Edges between clustered files aggregate into a single weighted edge between
the clusters; intra-cluster edges collapse to the cluster's self-loop and are
dropped.
"""

from __future__ import annotations

from collections import defaultdict

from codegraph.viz.models import GraphEdge, GraphNode


def cluster_key(path: str, depth: int) -> str | None:
    """Return the ``depth``-segment prefix, or None if the path is not deeper.

    ``cluster_key("a.py", 1)`` -> None (root files stay visible files);
    ``cluster_key("src/a.py", 1)`` -> "src".
    """
    parts = path.split("/")
    if len(parts) <= depth:
        return None
    return "/".join(parts[:depth])


def build_cluster_graph(
    nodes: list[GraphNode], edges: list[GraphEdge], depth: int
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Cluster ``nodes``/``edges`` at ``depth``; return sorted cluster nodes+edges."""
    path_by_id = {n.id: n.path or n.label for n in nodes}

    clusters: dict[str, int] = defaultdict(int)
    shallow: list[GraphNode] = []
    for n in nodes:
        key = cluster_key(n.path or n.label, depth)
        if key is None:
            shallow.append(n)
        else:
            clusters[key] += 1

    def resolve(nid: str) -> str:
        key = cluster_key(path_by_id[nid], depth)
        return f"dir:{key}" if key is not None else nid

    out_nodes: list[GraphNode] = shallow[:]
    out_nodes.extend(
        GraphNode(
            id=f"dir:{key}",
            kind="dir_cluster",
            label=key.rsplit("/", 1)[-1],
            path=key,
            file_count=count,
        )
        for key, count in sorted(clusters.items())
    )
    out_nodes.sort(key=lambda n: n.id)  # test asserts id-sorted output

    agg: dict[tuple[str, str], int] = defaultdict(int)
    for e in edges:
        s, t = resolve(e.source), resolve(e.target)
        if s == t:
            continue
        agg[(s, t)] += 1
    out_edges = [
        GraphEdge(source=s, target=t, type="IMPORTS", weight=w)
        for (s, t), w in sorted(agg.items())
    ]
    return out_nodes, out_edges
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_viz_clustering.py -v`
Expected: PASS (2 passed).

- [x] **Step 5: Commit**

```bash
git add src/codegraph/viz/clustering.py tests/unit/test_viz_clustering.py
git commit -m "feat(viz): pure directory clustering for overview view"
```

---

### Task 4: VizService query layer

**Files:**
- Create: `src/codegraph/viz/service.py`
- Test: `tests/unit/test_viz_service.py` (create)

**Interfaces:**
- Consumes: `Neo4jAdapter` (`_run_read`, `list_repos`, `search_nodes`, `find_file_dependencies`, `get_file_info`), `read_source_range(repos_dir, graph_id, file_path, start_line, end_line)`, models from Task 2, `build_cluster_graph` from Task 3.
- Produces: `VizService.__init__(self, adapter: Neo4jAdapter, repos_dir: Path)` with methods:
  - `async repos(self) -> list[dict[str, Any]]`
  - `async full_graph(self, graph_id: str, max_edges: int = 10_000) -> GraphPayload`
  - `async overview_graph(self, graph_id: str, depth: int = 1) -> GraphPayload`
  - `async subgraph(self, req: SubgraphRequest) -> GraphPayload`
  - `async impact(self, req: ImpactRequest) -> ImpactPayload`
  - `async expand_dir(self, graph_id: str, dir_prefix: str) -> ExpandResult`
  - `async search(self, graph_id: str, q: str, kind: str, limit: int = 20) -> list[dict[str, Any]]`
  - `async file_detail(self, repo: Repository-ish...) -> FileDetailResponse` — signature: `async file_detail(self, graph_id: str, file_path: str) -> FileDetailResponse`

Node-id conventions (must match frontend): file = `file:{path}`, symbol = `sym:{name}`, dir = `dir:{prefix}`. Node label for files = last path segment.

- [x] **Step 1: Write the failing test**

Create `tests/unit/test_viz_service.py`. A fake reader stands in for Neo4j:

```python
"""VizService query layer against a fake graph reader."""

from __future__ import annotations

import pytest

from codegraph.viz.models import ImpactRequest, SubgraphRequest
from codegraph.viz.service import VizService


class FakeAdapter:
    """Scripted stand-in for Neo4jAdapter implementing only what VizService uses.

    ``_run_read`` returns the rows of the FIRST dict key that appears in the
    Cypher, so keys must be listed most-specific-first and act as fingerprints
    of the query shape. See the dict literal in ``_fake`` below.
    """

    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self._rows = rows
        self.queries: list[str] = []

    async def _run_read(self, cypher: str, **params):
        self.queries.append(cypher)
        for key, rows in self._rows.items():
            if key in cypher:
                return rows
        return []

    async def list_repos(self):
        return [{"graph_id": "o/n", "name": "o/n", "url": "https://github.com/o/n"}]

    async def get_file_info(self, *, graph_id: str, file_path: str):
        if file_path != "auth.py":
            return None
        return {"path": "auth.py", "language": "python", "last_author": "a",
                "last_commit_at": None, "last_commit_sha": None}

    async def search_nodes(self, *, graph_id: str, query: str, kind: str, limit: int, offset: int = 0):
        return [{"id": "file:auth.py", "name": "auth.py", "kind": "file",
                 "path": "auth.py", "score": 1.0}]

    async def find_file_dependencies(self, *, graph_id: str, file_path: str, direction: str, max_hops: int):
        return {
            "file": {"path": file_path},
            "imported_by": [{"path": "api.py", "kind": "file", "via": "imported_by", "hop": 1}],
            "imports": [{"path": "db.py", "kind": "file", "via": "imports", "hop": 1}],
            "callers": [], "calls": [], "external_symbols": [{"name": "os", "kind": "import"}],
            "truncated": False, "hint": None,
        }


_FILES = [
    {"id": "n1", "path": "auth.py", "language": "python"},
    {"id": "n2", "path": "api.py", "language": "python"},
    {"id": "n3", "path": "db.py", "language": "python"},
    {"id": "n4", "path": "lib/util.py", "language": "python"},
]
_FF_EDGES = [{"src": "api.py", "dst": "auth.py"}, {"src": "auth.py", "dst": "db.py"},
             {"src": "api.py", "dst": "lib/util.py"}]
_FS_EDGES = [{"src": "auth.py", "name": "os", "kind": "import"}]
_SYMS = [{"name": "os", "kind": "import"}]
_CHAIN_IN = [{"chain": ["api.py", "auth.py"]}]          # api.py -IMPORTS-> auth.py
_CHAIN_OUT = [{"chain": ["auth.py", "db.py"]}]          # auth.py -IMPORTS-> db.py
_FNS = [{"name": "authenticate", "qualified_name": "auth.authenticate",
         "kind": "function", "start_line": 1, "end_line": 10}]


def _fake(tmp_path) -> FakeAdapter:
    # Keys are checked in order; each must be a substring unique to one query
    # shape (prefer the distinctive RETURN fragment), most-specific first.
    return FakeAdapter({
        "RETURN DISTINCT s.name": _SYMS,
        "RETURN a.path AS src, s.name AS name": _FS_EDGES,
        "RETURN a.path AS src, b.path AS dst": _FF_EDGES,
        "AS chain": _CHAIN_IN + _CHAIN_OUT,
        "f.path STARTS WITH $prefix": _FILES,
        "f.path IN $paths": _FILES,
        "RETURN fn.name AS name": _FNS,
        "RETURN elementId(f) AS id, f.path AS path": _FILES,
    })


def test_full_graph() -> None:
    svc = VizService(_fake(None), _TMP())
    out = asyncio_run(svc.full_graph("o/n"))
    assert out.view == "full"
    assert {n.path for n in out.nodes if n.kind == "file"} >= {"auth.py", "api.py", "db.py"}
    assert any(n.kind == "symbol" and n.path is None for n in out.nodes)
    assert any(e.type == "IMPORTS" for e in out.edges)
    assert out.stats.file_count == 4


def test_overview_clusters() -> None:
    svc = VizService(_fake(None), _TMP())
    out = asyncio_run(svc.overview_graph("o/n"))
    assert any(n.kind == "dir_cluster" and n.id == "dir:lib" for n in out.nodes)


def test_subgraph_builds_edges_from_chains() -> None:
    svc = VizService(_fake(None), _TMP())
    out = asyncio_run(svc.subgraph(SubgraphRequest(graph_id="o/n", seed_path="auth.py")))
    assert any(e.source == "file:api.py" and e.target == "file:auth.py" for e in out.edges)
    assert any(e.source == "file:auth.py" and e.target == "file:db.py" for e in out.edges)
    assert any(e.target == "sym:os" for e in out.edges)


def test_impact_rings() -> None:
    svc = VizService(_fake(None), _TMP())
    out = asyncio_run(svc.impact(ImpactRequest(graph_id="o/n", seed_path="auth.py", max_hops=2)))
    assert out.rings and out.rings[0].hop == 1
    assert "api.py" in out.rings[0].paths
    assert "db.py" in out.rings[0].paths
    assert "os" in out.external_symbols()


def test_file_detail_missing_file_raises() -> None:
    svc = VizService(_fake(None), _TMP())
    with pytest.raises(ValueError):
        asyncio_run(svc.file_detail("o/n", "nonexistent.py"))


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def _TMP():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())
```

Note: `out.external_symbols()` does not exist — the fake's symbols appear as `sym:` nodes; assert `any(n.kind == "symbol" for n in out.nodes)` instead (see Step 3 test fix below).

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_viz_service.py -v`
Expected: FAIL — `ModuleNotFoundError: codegraph.viz.service`.

- [x] **Step 3: Implement service.py**

Create `src/codegraph/viz/service.py`:

```python
"""VizService — read-only query layer backing the codegraph-viz REST API.

All Cypher lives here (parameterized, ``graph_id``-scoped) on top of the
existing Neo4jAdapter's ``_run_read`` helper. Variable-length relationship
bounds are the single allowed literal interpolation, validated before use
(mirrors ``_validated_hop_bound`` in the adapter).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from codegraph.models.common import MAX_TRAVERSAL_HOPS
from codegraph.repo.neo4j_adapter import Neo4jAdapter
from codegraph.source_reader import read_source_range
from codegraph.viz.clustering import build_cluster_graph
from codegraph.viz.models import (
    ExpandResult,
    FileDetailResponse,
    FunctionInfo,
    GraphEdge,
    GraphNode,
    GraphPayload,
    GraphStats,
    ImpactPayload,
    ImpactRequest,
    ImpactRing,
    SubgraphRequest,
)


def _hop_bound(depth: int) -> int:
    """Validate a hop/depth bound before splicing into a variable-length pattern."""
    if not isinstance(depth, int) or isinstance(depth, bool) or not (0 <= depth <= MAX_TRAVERSAL_HOPS):
        raise ValueError(f"depth must be an int in [0, {MAX_TRAVERSAL_HOPS}], got {depth!r}")
    return depth


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


class VizService:
    def __init__(self, adapter: Neo4jAdapter, repos_dir: Path) -> None:
        self._adapter = adapter
        self._repos_dir = repos_dir

    async def repos(self) -> list[dict[str, Any]]:
        return await self._adapter.list_repos()

    async def _load_full(
        self, graph_id: str
    ) -> tuple[list[GraphNode], list[GraphEdge], int]:
        """Every non-deleted File/Symbol node and every IMPORTS edge, uncapped.

        Split out of ``full_graph`` so ``overview_graph`` clusters the whole
        graph while ``full_graph`` caps what it ships to the browser.
        """
        files = await self._adapter._run_read(
            "MATCH (f:File {graph_id: $gid}) WHERE f.deleted = false "
            "RETURN elementId(f) AS id, f.path AS path, f.language AS language "
            "ORDER BY f.path",
            gid=graph_id,
        )
        ff = await self._adapter._run_read(
            "MATCH (a:File {graph_id: $gid})-[:IMPORTS]->(b:File {graph_id: $gid}) "
            "WHERE a.deleted = false AND b.deleted = false "
            "RETURN a.path AS src, b.path AS dst",
            gid=graph_id,
        )
        fs = await self._adapter._run_read(
            "MATCH (a:File {graph_id: $gid})-[:IMPORTS]->(s:Symbol {graph_id: $gid}) "
            "WHERE a.deleted = false "
            "RETURN a.path AS src, s.name AS name",
            gid=graph_id,
        )
        syms = await self._adapter._run_read(
            "MATCH (f:File {graph_id: $gid})-[:IMPORTS]->(s:Symbol {graph_id: $gid}) "
            "WHERE f.deleted = false "
            "RETURN DISTINCT s.name AS name ORDER BY s.name",
            gid=graph_id,
        )

        sym_ids = {row["name"]: f"sym:{row['name']}" for row in syms}
        nodes: list[GraphNode] = [
            GraphNode(id=f"file:{r['path']}", kind="file", label=_basename(r["path"]),
                      path=r["path"], language=r["language"])
            for r in files
        ]
        nodes.extend(
            GraphNode(id=f"sym:{r['name']}", kind="symbol", label=r["name"])
            for r in syms
        )
        edges: list[GraphEdge] = [
            GraphEdge(source=f"file:{r['src']}", target=f"file:{r['dst']}", type="IMPORTS")
            for r in ff
        ]
        edges.extend(
            GraphEdge(source=f"file:{r['src']}", target=sym_ids[r["name"]], type="IMPORTS")
            for r in fs
            if r["name"] in sym_ids
        )
        return nodes, edges, len(files)

    async def full_graph(self, graph_id: str, max_edges: int = 10_000) -> GraphPayload:
        nodes, edges, file_count = await self._load_full(graph_id)
        truncated = len(edges) > max_edges
        if truncated:
            # Actually cap the payload, don't just flag it: 5k-file repos can
            # carry ~20k edges and the browser has to lay every one of them
            # out. File nodes stay (they are the repo inventory); symbol nodes
            # whose only edge was cut would be orphans, so they go.
            edges = edges[:max_edges]
            keep = {e.source for e in edges} | {e.target for e in edges}
            nodes = [n for n in nodes if n.kind == "file" or n.id in keep]
        return GraphPayload(
            graph_id=graph_id,
            view="full",
            nodes=nodes,
            edges=edges,
            stats=GraphStats(
                file_count=file_count,
                edge_count=len(edges),
                truncated=truncated,
                view="full",
            ),
        )

    async def overview_graph(self, graph_id: str, depth: int = 1) -> GraphPayload:
        nodes_all, edges_all, file_count = await self._load_full(graph_id)
        nodes, edges = build_cluster_graph(nodes_all, edges_all, depth)
        return GraphPayload(
            graph_id=graph_id,
            view="overview",
            nodes=nodes,
            edges=edges,
            stats=GraphStats(
                file_count=file_count,
                edge_count=len(edges),
                truncated=False,
                view="overview",
            ),
        )

    async def subgraph(self, req: SubgraphRequest) -> GraphPayload:
        d = _hop_bound(req.depth)
        chains: list[list[str]] = []
        if req.direction in ("imported_by", "both"):
            chains.extend(
                row["chain"]
                for row in await self._adapter._run_read(
                    "MATCH (seed:File {graph_id: $gid, path: $p}) WHERE seed.deleted = false "
                    f"MATCH path = (src:File {{graph_id: $gid}})-[:IMPORTS*1..{d}]->(seed) "
                    "WHERE ALL(n IN nodes(path) WHERE n:File AND n.deleted = false) "
                    "RETURN [x IN nodes(path) | x.path] AS chain",
                    gid=req.graph_id, p=req.seed_path,
                )
            )
        if req.direction in ("imports", "both"):
            chains.extend(
                row["chain"]
                for row in await self._adapter._run_read(
                    "MATCH (seed:File {graph_id: $gid, path: $p}) WHERE seed.deleted = false "
                    f"MATCH path = (seed)-[:IMPORTS*1..{d}]->(tgt:File {{graph_id: $gid}}) "
                    "WHERE ALL(n IN nodes(path) WHERE n:File AND n.deleted = false) "
                    "RETURN [x IN nodes(path) | x.path] AS chain",
                    gid=req.graph_id, p=req.seed_path,
                )
            )

        paths = {p for chain in chains for p in chain}
        paths.add(req.seed_path)
        edges: list[GraphEdge] = []
        seen: set[tuple[str, str]] = set()
        for chain in chains:
            for src, tgt in zip(chain, chain[1:]):
                key = (src, tgt)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(GraphEdge(source=f"file:{src}", target=f"file:{tgt}", type="IMPORTS"))

        symbols: list[GraphEdge] = []
        if req.include_symbols:
            syms = await self._adapter._run_read(
                "MATCH (f:File {graph_id: $gid, path: $p})-[:IMPORTS]->(s:Symbol {graph_id: $gid}) "
                "WHERE f.deleted = false RETURN DISTINCT s.name AS name",
                gid=req.graph_id, p=req.seed_path,
            )
            for row in syms:
                symbols.append(GraphEdge(source=f"file:{req.seed_path}", target=f"sym:{row['name']}", type="IMPORTS"))
                paths.add(req.seed_path)  # ensure seed file node exists below

        lang_rows = await self._adapter._run_read(
            "MATCH (f:File {graph_id: $gid}) "
            "WHERE f.deleted = false AND f.path IN $paths "
            "RETURN f.path AS path, f.language AS language",
            gid=req.graph_id, paths=sorted(paths),
        )
        lang = {r["path"]: r["language"] for r in lang_rows}
        nodes: list[GraphNode] = [
            GraphNode(id=f"file:{p}", kind="file", label=_basename(p), path=p, language=lang.get(p))
            for p in sorted(paths)
        ]
        for e in symbols:
            name = e.target.rsplit(":", 1)[1]
            nodes.append(GraphNode(id=f"sym:{name}", kind="symbol", label=name))
        edges = _dedup_edges(edges + symbols)
        return GraphPayload(
            graph_id=req.graph_id,
            view="subgraph",
            nodes=_dedup_nodes(nodes),
            edges=edges,
            stats=GraphStats(file_count=len(paths), edge_count=len(edges), view="subgraph"),
        )

    async def impact(self, req: ImpactRequest) -> ImpactPayload:
        res = await self._adapter.find_file_dependencies(
            graph_id=req.graph_id, file_path=req.seed_path, direction="both", max_hops=req.max_hops
        )
        by_hop: dict[int, set[str]] = defaultdict(set)
        for entry in res["imported_by"] + res["imports"]:
            by_hop[entry["hop"]].add(entry["path"])
        rings = [ImpactRing(hop=h, paths=sorted(by_hop[h])) for h in sorted(by_hop)]
        callers = sorted({e["path"] for e in res["callers"]})
        calls = sorted({e["path"] for e in res["calls"]})
        return ImpactPayload(
            graph_id=req.graph_id,
            seed_path=req.seed_path,
            rings=rings,
            callers=callers,
            calls=calls,
            truncated=res["truncated"],
        )

    async def expand_dir(self, graph_id: str, dir_prefix: str) -> ExpandResult:
        """Expand one level: files directly in ``dir_prefix`` + child clusters.

        Returning every descendant would dump thousands of nodes on the canvas
        the moment a top-level directory of a big repo is clicked, which is the
        exact thing the overview view exists to avoid. Deeper files re-cluster
        at the next depth instead.
        """
        prefix = dir_prefix.strip("/")
        nodes_all, edges_all, _ = await self._load_full(graph_id)
        scope = f"{prefix}/" if prefix else ""
        inside = [
            n
            for n in nodes_all
            if n.kind == "file" and n.path is not None and n.path.startswith(scope)
        ]
        keep = {n.id for n in inside}
        inner = [e for e in edges_all if e.source in keep and e.target in keep]
        depth = len(prefix.split("/")) + 1 if prefix else 1
        nodes, edges = build_cluster_graph(inside, inner, depth)
        return ExpandResult(graph_id=graph_id, dir_prefix=prefix, nodes=nodes, edges=edges)

    async def search(self, graph_id: str, q: str, kind: str, limit: int = 20) -> list[dict[str, Any]]:
        return await self._adapter.search_nodes(graph_id=graph_id, query=q, kind=kind, limit=limit)

    async def file_detail(self, graph_id: str, file_path: str) -> FileDetailResponse:
        info = await self._adapter.get_file_info(graph_id=graph_id, file_path=file_path)
        if info is None:
            raise ValueError(
                f"File '{file_path}' not found in graph '{graph_id}' (or has been deleted). "
                "Use Search to confirm the path."
            )
        content, sl, el, truncated = read_source_range(
            self._repos_dir, graph_id, file_path, None, None
        )
        fns = await self._adapter._run_read(
            "MATCH (f:File {graph_id: $gid, path: $p})-[:DEFINES]->(fn:Function {graph_id: $gid}) "
            "WHERE f.deleted = false "
            "RETURN fn.name AS name, fn.qualified_name AS qualified_name, fn.kind AS kind, "
            "       fn.start_line AS start_line, fn.end_line AS end_line "
            "ORDER BY fn.start_line",
            gid=graph_id, p=file_path,
        )
        deps = await self._adapter.find_file_dependencies(
            graph_id=graph_id, file_path=file_path, direction="both", max_hops=1
        )
        return FileDetailResponse(
            graph_id=graph_id,
            path=info["path"],
            language=info.get("language"),
            last_author=info.get("last_author"),
            last_commit_at=info.get("last_commit_at"),
            last_commit_sha=info.get("last_commit_sha"),
            content=content,
            start_line=sl,
            end_line=el,
            truncated=truncated,
            functions=[FunctionInfo(**v) for v in fns],
            imported_by=sorted({e["path"] for e in deps["imported_by"]}),
            imports=sorted({e["path"] for e in deps["imports"]}),
            external_symbols=sorted({e["name"] for e in deps["external_symbols"]}),
        )


def _dedup_nodes(nodes: list[GraphNode]) -> list[GraphNode]:
    seen: dict[str, GraphNode] = {}
    for n in nodes:
        seen.setdefault(n.id, n)
    return list(seen.values())


def _dedup_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    seen: dict[tuple[str, str], GraphEdge] = {}
    for e in edges:
        key = (e.source, e.target)
        if key not in seen:
            seen[key] = e
    return list(seen.values())
```

Then fix the bug in the Step 1 test (`test_impact_rings` referenced `out.external_symbols()`). Replace that assertion with:

```python
    assert any(n.kind == "symbol" for n in out.nodes)  # not applicable to impact; see below
```

`ImpactPayload` has no `nodes`/`external_symbols` — impact returns `rings`/`callers`/`calls`. Correct the test to assert on the real fields:

```python
def test_impact_rings() -> None:
    svc = VizService(_fake(None), _TMP())
    out = asyncio_run(svc.impact(ImpactRequest(graph_id="o/n", seed_path="auth.py", max_hops=2)))
    assert out.rings and out.rings[0].hop == 1
    assert "api.py" in out.rings[0].paths
    assert "db.py" in out.rings[0].paths
    assert out.callers == []
    assert out.calls == []
```

(That is the final test content for `test_impact_rings`; replace the block in the file you wrote in Step 1 with this version.)

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_viz_service.py -v`
Expected: PASS. If `test_subgraph_builds_edges_from_chains` or `test_full_graph` fails, the fake's substring keys are misordered — service queries share fragments (`MATCH (f:File` appears in file, symbol, and language queries), so keys must be the *distinctive RETURN fragments* (as listed in `_fake` above), checked most-specific-first.

- [x] **Step 5: Lint + typecheck**

Run: `uv run ruff check src tests`
Run: `uv run mypy src`
Expected: both clean.

- [x] **Step 6: Commit**

```bash
git add src/codegraph/viz/service.py tests/unit/test_viz_service.py
git commit -m "feat(viz): VizService query layer over Neo4jAdapter"
```

---

### Task 5: FastAPI app + endpoints

**Files:**
- Create: `src/codegraph/viz/api.py`
- Test: `tests/unit/test_viz_api.py` (create)

**Interfaces:**
- Consumes: `create_app(settings, *, adapter=None) -> FastAPI` — builds lifespan, a `VizService`, registers endpoints, serves `vizui/dist/` statics if present, and routes 404/500 to `{"detail","hint"}`.
- Produces: routes consumed by the frontend:
  - `GET /api/repos`
  - `GET /api/graph?graph_id=&view=overview|full&depth=1`
  - `POST /api/subgraph` (body `SubgraphRequest`)
  - `POST /api/impact` (body `ImpactRequest`)
  - `GET /api/expand?graph_id=&dir=prefix`
  - `GET /api/search?graph_id=&q=&kind=&limit=`
  - `GET /api/file?graph_id=&path=`
  - `GET /` and `/assets/...` static frontend (see note)

- [x] **Step 1: Write the failing test**

Create `tests/unit/test_viz_api.py`:

```python
"""FastAPI app endpoints for codegraph-viz (offline, fake adapter)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from codegraph.config import Settings
from codegraph.viz.api import create_app


class FakeAdapter:
    def __init__(self) -> None:
        self.made: list[str] = []

    async def connect(self) -> None:
        self.made.append("connect")

    async def close(self) -> None:
        self.made.append("close")

    async def list_repos(self):
        return [{"graph_id": "o/n", "name": "o/n", "url": "https://github.com/o/n"}]

    async def _run_read(self, cypher: str, **params):
        if "RETURN DISTINCT s.name" in cypher:
            return [{"name": "os"}]
        if "RETURN fn.name" in cypher:
            return [{"name": "authenticate", "qualified_name": "auth.authenticate",
                     "kind": "function", "start_line": 1, "end_line": 10}]
        if "AS chain" in cypher:
            return [{"chain": ["api.py", "auth.py"]}]
        if "MATCH (f:File" in cypher:
            return [{"id": "n1", "path": "auth.py", "language": "python"},
                    {"id": "n2", "path": "api.py", "language": "python"}]
        if "f.path IN $paths" in cypher:
            return [{"path": "auth.py", "language": "python"},
                    {"path": "api.py", "language": "python"}]
        if "RETURN a.path AS src, s.name AS name" in cypher:
            return [{"src": "api.py", "name": "os"}]
        if "a.path AS src, b.path AS dst" in cypher:
            return [{"src": "api.py", "dst": "auth.py"}]
        return []

    async def get_file_info(self, *, graph_id: str, file_path: str):
        return {"path": file_path, "language": "python", "last_author": "x",
                "last_commit_at": None, "last_commit_sha": None}

    async def search_nodes(self, *, graph_id, query, kind, limit, offset=0):
        return [{"id": "file:auth.py", "name": "auth.py", "kind": "file",
                 "path": "auth.py", "score": 1.0}]

    async def find_file_dependencies(self, *, graph_id, file_path, direction, max_hops):
        return {"file": {"path": file_path}, "imported_by": [], "imports": [],
                "callers": [], "calls": [],
                "external_symbols": [{"name": "os", "kind": "import"}],
                "truncated": False, "hint": None}


@pytest.fixture()
def client(tmp_path):
    app = create_app(Settings(repos_dir=tmp_path, viz_host="127.0.0.1", viz_port=8787),
                     adapter=FakeAdapter())
    with TestClient(app) as c:
        yield c


def test_repos(client) -> None:
    r = client.get("/api/repos")
    assert r.status_code == 200
    assert r.json()[0]["graph_id"] == "o/n"


def test_graph_full(client) -> None:
    r = client.get("/api/graph", params={"graph_id": "o/n", "view": "full"})
    assert r.status_code == 200
    body = r.json()
    assert body["view"] == "full"
    assert any(n["kind"] == "symbol" for n in body["nodes"])


def test_graph_overview(client) -> None:
    r = client.get("/api/graph", params={"graph_id": "o/n", "view": "overview"})
    assert r.status_code == 200
    assert r.json()["view"] == "overview"


def test_subgraph_endpoint(client) -> None:
    r = client.post("/api/subgraph", json={"graph_id": "o/n", "seed_path": "auth.py", "depth": 2})
    assert r.status_code == 200
    assert any(e["source"] == "file:api.py" for e in r.json()["edges"])


def test_impact_endpoint(client) -> None:
    r = client.post("/api/impact", json={"graph_id": "o/n", "seed_path": "auth.py", "max_hops": 2})
    assert r.status_code == 200
    assert r.json()["seed_path"] == "auth.py"


def test_search_endpoint(client) -> None:
    r = client.get("/api/search", params={"graph_id": "o/n", "q": "auth", "kind": "file"})
    assert r.status_code == 200
    assert r.json()[0]["name"] == "auth.py"


def test_file_detail_endpoint(client, tmp_path) -> None:
    repo_dir = tmp_path / "o__n"
    repo_dir.mkdir(parents=True)
    (repo_dir / "auth.py").write_text("def authenticate():\n    return 'ok'\n", encoding="utf-8")
    r = client.get("/api/file", params={"graph_id": "o/n", "path": "auth.py"})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "auth.py"
    assert body["functions"][0]["name"] == "authenticate"


def test_file_detail_missing_is_404_with_hint(client) -> None:
    class Boom(FakeAdapter):
        async def get_file_info(self, *, graph_id: str, file_path: str):
            return None

    app = create_app(Settings(repos_dir=tmp_factory(), viz_port=8787), adapter=Boom())
    with TestClient(app) as c:
        r = c.get("/api/file", params={"graph_id": "o/n", "path": "nope.py"})
    assert r.status_code == 404
    assert "hint" in r.json()


def test_unknown_graph_route_is_404(client) -> None:
    r = client.get("/api/doesnotexist")
    assert r.status_code == 404


def tmp_factory():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())
```

Note: `test_file_detail_missing_is_404_with_hint` uses a local `tmp_path`-independent helper because it constructs its own app; keep it as written. The `Settings()` constructor in `create_app` calls must include `repos_dir` since `repos_dir` default is `Path("./repos")` (relative path is fine for tests, but tmp_path keeps it hermetic).

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_viz_api.py -v`
Expected: FAIL — `ModuleNotFoundError: codegraph.viz.api`.

- [x] **Step 3: Implement api.py**

Create `src/codegraph/viz/api.py`:

```python
"""FastAPI application for codegraph-viz (read-only web UI over Neo4j).

The app is built by ``create_app`` so tests inject a fake adapter. In
production the CLI wires ``Settings`` + a real ``Neo4jAdapter`` under uvicorn.
The MCP stdio server is a separate process and is never touched here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from codegraph.config import Settings
from codegraph.repo.neo4j_adapter import Neo4jAdapter
from codegraph.viz.models import ImpactRequest, SubgraphRequest
from codegraph.viz.service import VizService

_DIST = Path(__file__).resolve().parents[3] / "vizui" / "dist"


def create_app(settings: Settings, *, adapter: Neo4jAdapter | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo = adapter
        if repo is None:
            repo = Neo4jAdapter.from_settings(settings)
            await repo.connect()
        app.state.service = VizService(repo, settings.repos_dir)
        yield
        if adapter is None:
            await repo.close()

    app = FastAPI(title="codegraph-viz", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _svc() -> VizService:
        return app.state.service  # type: ignore[no-any-return]

    def _err(status: int, detail: str, hint: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": detail, "hint": hint})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Any, exc: RequestValidationError) -> JSONResponse:
        return _err(422, "invalid request arguments", f"Fix the request body/params: {exc.errors()}")

    @app.exception_handler(ValueError)
    async def _value_error(_req: Any, exc: ValueError) -> JSONResponse:
        return _err(404, str(exc), "Check the path exists in the selected repository.")

    @app.exception_handler(Exception)
    async def _unhandled(_req: Any, _exc: Exception) -> JSONResponse:
        return _err(
            500,
            "internal error",
            "The Neo4j database may be down — run `make up` to start it, then retry.",
        )

    @app.get("/api/repos")
    async def repos() -> list[dict[str, Any]]:
        return await _svc().repos()

    # graph_id is a repo slug like `github.com/owner/name` — it contains
    # slashes, and the ASGI server percent-decodes the path before routing, so
    # `%2F` does not help. Every endpoint takes graph_id as a QUERY parameter.
    @app.get("/api/graph")
    async def graph(
        graph_id: str,
        view: str = Query("overview", pattern="^(overview|full)$"),
        depth: int = Query(1, ge=1, le=10),
    ) -> Any:
        if view == "full":
            return await _svc().full_graph(graph_id)
        return await _svc().overview_graph(graph_id, depth=depth)

    @app.post("/api/subgraph")
    async def subgraph(req: SubgraphRequest) -> Any:
        return await _svc().subgraph(req)

    @app.post("/api/impact")
    async def impact(req: ImpactRequest) -> Any:
        return await _svc().impact(req)

    @app.get("/api/expand")
    async def expand(graph_id: str, dir: str = Query("")) -> Any:
        return await _svc().expand_dir(graph_id, dir)

    @app.get("/api/search")
    async def search(
        graph_id: str,
        q: str,
        kind: str = Query("any", pattern="^(any|function|file)$"),
        limit: int = Query(20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return await _svc().search(graph_id, q, kind, limit)

    @app.get("/api/file")
    async def file_detail(graph_id: str, path: str) -> Any:
        return await _svc().file_detail(graph_id, path)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA when present (prod); otherwise just the API."""
    if not _DIST.exists():
        @app.get("/", include_in_schema=False)
        async def _no_ui() -> JSONResponse:
            return JSONResponse(
                content={
                    "detail": "frontend not built",
                    "hint": "Run `make viz-build` (or `npm run dev` in vizui/ for dev mode).",
                }
            )
        return
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def _index() -> FileResponse:
        return FileResponse(_DIST / "index.html")
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_viz_api.py -v`
Expected: PASS. If validation errors surface as 422 instead of handler output, adjust assertions to `r.status_code == 422` only where intentional (the ValueError handler test expects 404).

- [x] **Step 5: Lint + typecheck**

Run: `uv run ruff check src tests`
Run: `uv run mypy src`
Expected: clean. If mypy complains about `app.state.service` dynamic attr, add `app.state.service = None  # type: ignore` — no, keep `Any` typing on `_svc`; FastAPI's `state` is `Any`-typed already.

- [x] **Step 6: Commit**

```bash
git add src/codegraph/viz/api.py tests/unit/test_viz_api.py
git commit -m "feat(viz): FastAPI REST app for the graph viewer"
```

---

### Task 6: `codegraph viz` CLI subcommand

**Files:**
- Modify: `src/codegraph/cli.py:13-37` (add subparser), `src/codegraph/cli.py:220-236` (dispatch), add `_cmd_viz`
- Test: `tests/unit/test_cli.py` (add 2 tests)

**Interfaces:**
- Consumes: `create_app` from Task 5, `Settings`.
- Produces: `codegraph viz [--host H] [--port P]` — runs uvicorn bound to `args.host or Settings.viz_host` / `args.port or Settings.viz_port`.

- [x] **Step 1: Write the failing test**

Append to `tests/unit/test_cli.py`:

```python
def test_cli_viz_parser_exposes_host_port() -> None:
    from codegraph.cli import _build_parser

    args = _build_parser().parse_args(["viz", "--host", "0.0.0.0", "--port", "9999"])
    assert args.cmd == "viz"
    assert args.host == "0.0.0.0"
    assert args.port == 9999


def test_cli_viz_defaults_host_port_to_none() -> None:
    from codegraph.cli import _build_parser, _cmd_viz

    args = _build_parser().parse_args(["viz"])
    assert args.host is None
    assert args.port is None
    assert callable(_cmd_viz)
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: FAIL — parser rejects `viz` / `_cmd_viz` undefined.

- [x] **Step 3: Wire the subcommand**

In `_build_parser` (after `sub.add_parser("ls", ...)` at `cli.py:36-37`):

```python
    viz = sub.add_parser("viz", help="Run the local web UI (browser graph viewer)")
    viz.add_argument("--host", default=None, help="Bind host (default: Settings.viz_host)")
    viz.add_argument("--port", type=int, default=None, help="Bind port (default: Settings.viz_port)")
```

Add `_cmd_viz` after `_cmd_ls`:

```python
def _cmd_viz(args: argparse.Namespace) -> int:
    import uvicorn

    from codegraph.config import Settings
    from codegraph.viz.api import create_app

    s = Settings()
    app = create_app(s)
    uvicorn.run(app, host=args.host or s.viz_host, port=args.port or s.viz_port, log_level="info")
    return 0
```

In `main()` dispatch (before the final `return 0`):

```python
    if args.cmd == "viz":
        return _cmd_viz(args)
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/codegraph/cli.py tests/unit/test_cli.py
git commit -m "feat(viz): codegraph viz CLI subcommand"
```

---

### Task 7: Integration tests against live Neo4j

**Files:**
- Test: `tests/integration/test_viz_endpoints.py` (create)

**Interfaces:**
- Consumes: the existing `adapter` and `fresh_graph_id` fixtures from `tests/integration/conftest.py`; `VizService` from Task 4.

- [x] **Step 1: Write the test**

Create `tests/integration/test_viz_endpoints.py`:

```python
"""viz service + REST endpoints against a live Neo4j (testcontainers)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def _seed(adapter, gid: str) -> None:
    """auth.py imports os (symbol); api.py imports auth.py; src/util.py standalone."""
    await adapter._run_write(
        "MERGE (r:Repository {graph_id: $gid}) "
        "MERGE (auth:File {graph_id: $gid, path: 'auth.py'}) "
        "  SET auth.language = 'python', auth.deleted = false "
        "MERGE (api:File {graph_id: $gid, path: 'api.py'}) "
        "  SET api.language = 'python', api.deleted = false "
        "MERGE (util:File {graph_id: $gid, path: 'src/util.py'}) "
        "  SET util.language = 'python', util.deleted = false "
        "MERGE (fn:Function {graph_id: $gid, qualified_name: 'auth.authenticate'}) "
        "  SET fn.name = 'authenticate', fn.kind = 'function', "
        "      fn.start_line = 1, fn.end_line = 10 "
        "MERGE (sym:Symbol {graph_id: $gid, name: 'os'}) SET sym.kind = 'import' "
        "MERGE (r)-[:CONTAINS]->(auth) "
        "MERGE (r)-[:CONTAINS]->(api) "
        "MERGE (r)-[:CONTAINS]->(util) "
        "MERGE (auth)-[:DEFINES]->(fn) "
        "MERGE (api)-[:IMPORTS]->(auth) "
        "MERGE (auth)-[:IMPORTS]->(sym)",
        gid=gid,
    )


async def test_viz_full_graph(adapter, fresh_graph_id) -> None:
    await _seed(adapter, fresh_graph_id)
    from pathlib import Path

    from codegraph.viz.service import VizService

    svc = VizService(adapter, Path("./repos"))
    out = await svc.full_graph(fresh_graph_id)
    paths = {n.path for n in out.nodes if n.kind == "file"}
    assert {"auth.py", "api.py", "src/util.py"} <= paths
    assert any(n.kind == "symbol" and n.label == "os" for n in out.nodes)
    assert any(e.source == "file:api.py" and e.target == "file:auth.py" for e in out.edges)
    assert any(e.source == "file:auth.py" and e.target == "sym:os" for e in out.edges)


async def test_viz_overview_clusters(adapter, fresh_graph_id) -> None:
    await _seed(adapter, fresh_graph_id)
    from pathlib import Path

    from codegraph.viz.service import VizService

    svc = VizService(adapter, Path("./repos"))
    out = await svc.overview_graph(fresh_graph_id, depth=1)
    clusters = {n.id for n in out.nodes if n.kind == "dir_cluster"}
    assert "dir:src" in clusters


async def test_viz_subgraph_and_impact(adapter, fresh_graph_id) -> None:
    await _seed(adapter, fresh_graph_id)
    from pathlib import Path

    from codegraph.viz.models import ImpactRequest, SubgraphRequest
    from codegraph.viz.service import VizService

    svc = VizService(adapter, Path("./repos"))
    sub = await svc.subgraph(
        SubgraphRequest(graph_id=fresh_graph_id, seed_path="auth.py", depth=2, include_symbols=True)
    )
    assert any(e.source == "file:api.py" and e.target == "file:auth.py" for e in sub.edges)
    assert any(e.target == "sym:os" for e in sub.edges)

    imp = await svc.impact(
        ImpactRequest(graph_id=fresh_graph_id, seed_path="auth.py", max_hops=2)
    )
    ring_paths = {p for r in imp.rings for p in r.paths}
    assert "api.py" in ring_paths
```

- [x] **Step 2: Run the integration test**

Requires Neo4j: `uv run pytest tests/integration/test_viz_endpoints.py -v` (needs Docker daemon + testcontainers, or `NEO4J_URI` env set).
Expected: PASS (3 passed).

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_viz_endpoints.py
git commit -m "test(viz): integration tests over live Neo4j"
```

---

### Task 8: Frontend scaffold (Vite + React + TS + Cytoscape)

**Files:**
- Create: `vizui/package.json`, `vizui/vite.config.ts`, `vizui/tsconfig.json`, `vizui/index.html`, `vizui/src/main.tsx`, `vizui/src/App.tsx`, `vizui/src/vite-env.d.ts`, `vizui/.gitignore`
- Modify: root `.gitignore` (add `vizui/node_modules`, `vizui/dist`)

**Interfaces:**
- Produces: a Vite dev server on `:5173` proxying `/api` → `http://127.0.0.1:8787`; `npm run build` → `vizui/dist`; `npm test` runs Vitest; React 18 + TypeScript + Cytoscape + cytoscape-fcose installed.

- [x] **Step 1: Create package.json**

Create `vizui/package.json`:

```json
{
  "name": "codegraph-viz-ui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "typecheck": "tsc --noEmit",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "cytoscape": "^3.30.2",
    "cytoscape-fcose": "^2.2.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/cytoscape": "^3.21.7",
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.6.2",
    "vite": "^5.4.8",
    "vitest": "^2.1.1"
  }
}
```

- [x] **Step 2: Create config files**

`vizui/vite.config.ts`:

```ts
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8787' },
  },
  test: { environment: 'node' },
})
```

`vizui/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "noEmit": true
  },
  "include": ["src"]
}
```

`vizui/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>codegraph-viz</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`vizui/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

`vizui/src/main.tsx`:

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

`vizui/.gitignore` and append to root `.gitignore`:

```
node_modules/
dist/
```

- [x] **Step 3: Minimal App.tsx (placeholder)**

`vizui/src/App.tsx`:

```tsx
export function App() {
  return <main style={{ fontFamily: 'monospace', padding: 24 }}>codegraph-viz — scaffold OK</main>
}
```

`vizui/src/styles.css` placeholder:

```css
:root { color-scheme: dark; }
html, body, #root { height: 100%; margin: 0; background: #101418; color: #e8e8e8; }
```

- [x] **Step 4: Install + build + test commands**

Run: `npm install` in `vizui/`
Run: `npm run build`
Run: `npm run typecheck`
Expected: build succeeds, typecheck clean, and `node_modules/` + `dist/` are gitignored.

- [x] **Step 5: Commit**

```bash
git add vizui .gitignore
git commit -m "feat(viz): frontend scaffold (Vite + React + TS + Cytoscape)"
```

---

### Task 9: Types, API client, and cytoscape element mapping

**Files:**
- Create: `vizui/src/types.ts`, `vizui/src/api.ts`, `vizui/src/graph/toCytoscape.ts`, `vizui/src/graph/theme.ts`
- Test: `vizui/src/graph/toCytoscape.test.ts` (create)

**Interfaces:**
- Consumes: backend wire format from Task 2 (same JSON shape).
- Produces:
  - `types.ts`: `GraphNode/GraphEdge/GraphStats/GraphPayload/SubgraphRequest/ImpactRequest/ImpactRing/ImpactPayload/ExpandResult/FunctionInfo/FileDetail/RepoInfo/SearchHit`;
  - `api.ts`: `fetchGraph(graphId, view, depth?)`, `fetchSubgraph(req)`, `fetchImpact(req)`, `expandDir(graphId, dir)`, `search(graphId, q)`, `fetchFileDetail(graphId, path)`, `fetchRepos()`;
  - `toCytoscape.ts`: `toElements(payload: GraphPayload): Cytoscape.ElementDefinition[]`;
  - `theme.ts`: `nodeColor(node)` and `label` helpers.

- [x] **Step 1: Write the failing mapping test**

Create `vizui/src/graph/toCytoscape.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { GraphPayload } from '../types'
import { toElements } from './toCytoscape'

const payload: GraphPayload = {
  graph_id: 'o/n',
  view: 'full',
  nodes: [
    { id: 'file:a.py', kind: 'file', label: 'a.py', path: 'a.py', language: 'python' },
    { id: 'sym:os', kind: 'symbol', label: 'os', path: null, language: null, file_count: null },
    { id: 'dir:src', kind: 'dir_cluster', label: 'src', path: 'src', language: null, file_count: 3 },
  ],
  edges: [{ source: 'file:a.py', target: 'sym:os', type: 'IMPORTS', weight: 1 }],
  stats: { file_count: 1, edge_count: 1, truncated: false, view: 'full' },
}

describe('toElements', () => {
  it('maps nodes to cytoscape data with classes', () => {
    const els = toElements(payload)
    const nodeEls = els.filter((e) => 'data' in e && (e.data as { id?: string }).id?.startsWith('file:'))
    expect(nodeEls).toHaveLength(1)
    const n = nodeEls[0]
    expect((n.data as { id: string }).id).toBe('file:a.py')
    expect((n.data as { path?: string }).path).toBe('a.py')
    expect((n.classes as string).split(' ')).toContain('node-file')
    expect((n.classes as string).split(' ')).toContain('lang-python')
  })

  it('maps edges with source/target and type class', () => {
    const els = toElements(payload)
    const edge = els.find((e) => 'source' in (e.data ?? {}))!
    expect(edge.data.source).toBe('file:a.py')
    expect(edge.data.target).toBe('sym:os')
    expect((edge.classes as string).split(' ')).toContain('edge-IMPORTS')
  })

  it('gives every element a unique id', () => {
    const ids = toElements(payload).map((e) => (e.data as { id?: string }).id).filter(Boolean)
    expect(new Set(ids).size).toBe(ids.length)
  })
})
```

- [x] **Step 2: Run test to verify it fails**

Run: `npm test` in `vizui/`
Expected: FAIL — `Cannot find module './toCytoscape'`.

- [x] **Step 3: Implement the modules**

`vizui/src/types.ts`:

```ts
export type GraphNodeKind = 'file' | 'dir_cluster' | 'symbol' | 'function'

export interface GraphNode {
  id: string
  kind: GraphNodeKind
  label: string
  path: string | null
  language: string | null
  file_count: number | null
}

export interface GraphEdge {
  source: string
  target: string
  type: 'IMPORTS' | 'CALLS' | 'DEFINES'
  weight: number
}

export interface GraphStats {
  file_count: number
  edge_count: number
  truncated: boolean
  view: string
}

export interface GraphPayload {
  graph_id: string
  view: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats: GraphStats
}

export interface SubgraphRequest {
  graph_id: string
  seed_path: string
  direction: 'imports' | 'imported_by' | 'both'
  depth: number
  include_symbols: boolean
}

export interface ImpactRequest {
  graph_id: string
  seed_path: string
  max_hops: number
}

export interface ImpactRing {
  hop: number
  paths: string[]
}

export interface ImpactPayload {
  graph_id: string
  seed_path: string
  rings: ImpactRing[]
  callers: string[]
  calls: string[]
  truncated: boolean
}

export interface ExpandResult {
  graph_id: string
  dir_prefix: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface FunctionInfo {
  name: string
  qualified_name: string
  kind: string
  start_line: number
  end_line: number
}

export interface FileDetail {
  graph_id: string
  path: string
  language: string | null
  last_author: string | null
  last_commit_at: string | null
  last_commit_sha: string | null
  content: string
  start_line: number
  end_line: number
  truncated: boolean
  functions: FunctionInfo[]
  imported_by: string[]
  imports: string[]
  external_symbols: string[]
}

export interface RepoInfo {
  graph_id: string
  name: string
  url: string
  default_branch: string | null
  ingested_at: string | null
  ingest_status: string
}

export interface SearchHit {
  id: string
  name: string
  kind: string
  path: string
  score: number
}
```

`vizui/src/api.ts`:

```ts
import type { ExpandResult, FileDetail, GraphPayload, ImpactPayload, ImpactRequest, RepoInfo, SearchHit, SubgraphRequest } from './types'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    let hint = ''
    try {
      const body = await res.json()
      detail = body.detail ?? detail
      hint = body.hint ?? ''
    } catch {
      /* non-JSON error body */
    }
    throw new Error(hint ? `${detail} — ${hint}` : detail)
  }
  return res.json() as Promise<T>
}

export async function fetchRepos(): Promise<RepoInfo[]> {
  return json(await fetch('/api/repos'))
}

export async function fetchGraph(graphId: string, view: 'overview' | 'full', depth = 1): Promise<GraphPayload> {
  // graph_id carries slashes (`github.com/owner/name`) so it is always a
  // query param, never a path segment.
  const qs = new URLSearchParams({ graph_id: graphId, view, depth: String(depth) })
  return json(await fetch(`/api/graph?${qs}`))
}

export async function fetchSubgraph(req: SubgraphRequest): Promise<GraphPayload> {
  return json(await fetch('/api/subgraph', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  }))
}

export async function fetchImpact(req: ImpactRequest): Promise<ImpactPayload> {
  return json(await fetch('/api/impact', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  }))
}

export async function expandDir(graphId: string, dir: string): Promise<ExpandResult> {
  const qs = new URLSearchParams({ graph_id: graphId, dir })
  return json(await fetch(`/api/expand?${qs}`))
}

export async function search(graphId: string, q: string): Promise<SearchHit[]> {
  return json(await fetch(`/api/search?graph_id=${encodeURIComponent(graphId)}&q=${encodeURIComponent(q)}&kind=any&limit=20`))
}

export async function fetchFileDetail(graphId: string, path: string): Promise<FileDetail> {
  const qs = new URLSearchParams({ graph_id: graphId, path })
  return json(await fetch(`/api/file?${qs}`))
}
```

`vizui/src/graph/theme.ts`:

```ts
import type { GraphNode } from '../types'

export const LANGUAGE_COLORS: Record<string, string> = {
  python: '#4B8BBE',
  javascript: '#F7DF1E',
  typescript: '#3178C6',
  java: '#E76F00',
  kotlin: '#7F52FF',
}

export const KIND_COLORS: Record<string, string> = {
  file: '#3E8FB0',
  dir_cluster: '#7A5CF0',
  symbol: '#C96A4B',
  function: '#4CAF88',
}

export function nodeBaseColor(node: GraphNode): string {
  if (node.kind === 'file' && node.language && LANGUAGE_COLORS[node.language]) {
    return LANGUAGE_COLORS[node.language]
  }
  return KIND_COLORS[node.kind] ?? '#888'
}
```

`vizui/src/graph/toCytoscape.ts`:

```ts
import type { ElementDefinition } from 'cytoscape'
import type { GraphEdge, GraphNode, GraphPayload } from '../types'
import { nodeBaseColor } from './theme'

export function nodeClassName(n: GraphNode): string {
  const parts = [`node-${n.kind}`]
  if (n.language) parts.push(`lang-${n.language}`)
  return parts.join(' ')
}

export function edgeClassName(e: GraphEdge): string {
  return `edge-${e.type}`
}

export function toElements(payload: GraphPayload): ElementDefinition[] {
  const nodeEls: ElementDefinition[] = payload.nodes.map((n) => ({
    data: {
      id: n.id,
      kind: n.kind,
      label: n.label,
      path: n.path ?? undefined,
      language: n.language ?? undefined,
      fileCount: n.file_count ?? undefined,
      color: nodeBaseColor(n),
    },
    classes: nodeClassName(n),
  }))
  const edgeEls: ElementDefinition[] = payload.edges.map((e, i) => ({
    data: {
      id: `${e.source}>${e.target}:${i}`,
      source: e.source,
      target: e.target,
      edgeType: e.type,
      weight: e.weight,
    },
    classes: edgeClassName(e),
  }))
  return [...nodeEls, ...edgeEls]
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `npm test` then `npm run typecheck` in `vizui/`
Expected: PASS (3 tests), typecheck clean.

- [x] **Step 5: Commit**

```bash
git add vizui/src
git commit -m "feat(viz): graph payload -> cytoscape element mapping"
```

---

### Task 10: GraphCanvas — cytoscape renderer with interactions

**Files:**
- Create: `vizui/src/graph/style.ts`, `vizui/src/graph/FlowOverlay.ts`, `vizui/src/components/GraphCanvas.tsx`, `vizui/src/components/Minimap.tsx`
- Modify: `vizui/src/App.tsx` (mount canvas with candidate state), `vizui/src/styles.css`

**Interfaces:**
- Consumes: `toElements` (Task 9), `GraphPayload`.
- Produces: `<GraphCanvas elements zoomOn={...} layout selectedNodeId onNodeSelect onNodeHover onFocusXYZ ... />` with these props:

```ts
export interface GraphCanvasProps {
  elements: ElementDefinition[]
  layout: 'fcose' | 'concentric' | 'breadthfirst'
  selectedNodeId: string | null
  highlightedNodeId: string | null // impact/neighborhood seed
  overlayNodeId: string | null     // impact set ring focus
  onNodeSelect: (id: string | null) => void
  onNodeHover: (id: string | null) => void
  focusRequest: { id: string; nonce: number } | null
}
```

Behaviors required: zoom/pan; **zoom-gated labels** (labels appear only past zoom ≥ ~0.9 via `style` function reading `ele.cy().zoom()`); directional arrowheads; neighborhood highlight on `selectedNodeId` (blue-out / red-in, others `.faded`); `FlowOverlay` particle animation between hover node and its direct neighbors; minimap; layout switcher re-runs layout; `focusRequest` centers+zooms on that node.

- [x] **Step 1: Create style module**

`vizui/src/graph/style.ts`:

```ts
import type { SingularElement, Stylesheet } from 'cytoscape'

const LABEL_MIN_ZOOM = 0.9

export const LABEL_FN = (ele: SingularElement): string => {
  const z = typeof ele.cy === 'function' ? ele.cy().zoom() : 1
  return z >= LABEL_MIN_ZOOM ? (ele.data('label') as string) : ''
}

export const buildStyle = (): Stylesheet[] => [
  {
    selector: 'core',
    style: { 'active-bg-opacity': 0.05 },
  },
  {
    selector: 'node',
    style: {
      width: 18,
      height: 18,
      'background-color': 'data(color)',
      label: LABEL_FN,
      'font-size': 11,
      'text-valign': 'bottom',
      'text-margin-y': 6,
      color: '#d8d8d8',
      'overlay-opacity': 0.15,
    },
  },
  {
    selector: 'node.node-symbol',
    style: { shape: 'rectangle', width: 26, height: 14, label: 'data(label)' },
  },
  {
    selector: 'node.node-dir_cluster',
    style: {
      shape: 'round-rectangle',
      width: 34,
      height: 22,
      'border-width': 2,
      'border-color': 'data(color)',
      'background-color': '#232a36',
      label: `data(label)`,
    },
  },
  {
    selector: 'node.selected',
    style: { 'border-width': 3, 'border-color': '#ffffff' },
  },
  {
    selector: 'node.faded, edge.faded',
    style: { opacity: 0.08 },
  },
  {
    selector: 'edge',
    style: {
      width: 1.5,
      'line-color': '#5a6572',
      'target-arrow-color': '#5a6572',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.1,
      'curve-style': 'bezier',
    },
  },
  {
    selector: 'edge.edge-IMPORTS',
    style: { 'line-color': '#4e7fa5', 'target-arrow-color': '#4e7fa5' },
  },
  {
    selector: 'edge.out',
    style: { 'line-color': '#3f7ef7', 'target-arrow-color': '#3f7ef7', width: 2.4 },
  },
  {
    selector: 'edge.in',
    style: { 'line-color': '#ef5350', 'target-arrow-color': '#ef5350', width: 2.4 },
  },
]
```

- [x] **Step 2: Create FlowOverlay (canvas particle animation)**

`vizui/src/graph/FlowOverlay.ts`:

```ts
import type { Core, NodeSingular } from 'cytoscape'

let raf = 0
let offsets: number[] = []
let active = false

export function startFlow(cy: Core, nodeId: string | null): void {
  const canvas = document.getElementById('flow-canvas') as HTMLCanvasElement | null
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx || !nodeId) {
    stopFlow()
    return
  }
  const ele = cy.$id(nodeId)
  if (ele.empty()) {
    stopFlow()
    return
  }
  const neighbours: NodeSingular[] = ele
    .connectedEdges()
    .map((e) => e.otherNode(ele))
    .filter((n) => !n.empty())
  offsets = neighbours.map((_, i) => (i % 12) / 12)
  active = true
  cancelAnimationFrame(raf)
  const tick = (): void => {
    // The canvas is CSS-stretched over the cytoscape viewport but its bitmap
    // defaults to 300x150 — without this sync the particles are drawn to a
    // different coordinate space than the one the user sees.
    if (canvas.width !== canvas.clientWidth) canvas.width = canvas.clientWidth
    if (canvas.height !== canvas.clientHeight) canvas.height = canvas.clientHeight
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    // Positions are re-read every frame so the particles track pan and zoom.
    const from = ele.renderedPosition()
    neighbours.forEach((n, i) => {
      const to = n.renderedPosition()
      offsets[i] = (offsets[i] + 0.01) % 1
      const t = offsets[i]
      ctx.beginPath()
      ctx.arc(from.x + (to.x - from.x) * t, from.y + (to.y - from.y) * t, 2.2, 0, Math.PI * 2)
      ctx.fillStyle = '#7fc4ff'
      ctx.fill()
    })
    if (active) raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
}

export function stopFlow(): void {
  active = false
  cancelAnimationFrame(raf)
  const canvas = document.getElementById('flow-canvas') as HTMLCanvasElement | null
  canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height)
}
```

- [x] **Step 3: Create Minimap**

`vizui/src/components/Minimap.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import type { Core } from 'cytoscape'

export function Minimap({ cy }: { cy: Core | null }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (!cy || !ref.current) return
    const cv = ref.current
    const draw = (): void => {
      const ctx = cv.getContext('2d')
      if (!ctx) return
      const bb = cy.elements().boundingBox()
      ctx.clearRect(0, 0, cv.width, cv.height)
      if (bb.w === 0 || bb.h === 0) return
      const s = Math.min(cv.width / bb.w, cv.height / bb.h)
      ctx.fillStyle = '#2a3340'
      cy.nodes().forEach((n) => {
        const p = n.position()
        ctx.fillStyle = n.data('color') as string
        ctx.fillRect((p.x - bb.x1) * s, (p.y - bb.y1) * s, 2.4, 2.4)
      })
    }
    cy.on('render', draw)
    return () => {
      cy.off('render', draw)
    }
  }, [cy])

  return (
    <canvas
      ref={ref}
      id="minimap"
      width={180}
      height={120}
      style={{
        position: 'absolute',
        right: 8,
        bottom: 8,
        width: 180,
        height: 120,
        border: '1px solid #39424f',
        background: '#101418',
        zIndex: 10,
        borderRadius: 6,
      }}
    />
  )
}
```

- [x] **Step 4: Create GraphCanvas**

`vizui/src/components/GraphCanvas.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import cytoscape, {
  type Core,
  type ElementDefinition,
  type EventObject,
  type NodeSingular,
} from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { buildStyle } from '../graph/style'
import { startFlow, stopFlow } from '../graph/FlowOverlay'
import { Minimap } from './Minimap'

cytoscape.use(fcose)

export interface GraphCanvasProps {
  elements: ElementDefinition[]
  layout: 'fcose' | 'concentric' | 'breadthfirst'
  selectedNodeId: string | null
  onNodeSelect: (id: string | null) => void
  onNodeHover: (id: string | null) => void
  focusRequest: { id: string; nonce: number } | null
}

export function GraphCanvas(props: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  // Also held in state: mutating a ref never triggers a render, so a minimap
  // gated on `cyRef.current` would never mount.
  const [cyReady, setCyReady] = useState<Core | null>(null)
  const propsRef = useRef(props)
  propsRef.current = props

  useEffect(() => {
    if (!containerRef.current) return
    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: buildStyle(),
      layout: { name: 'fcose' },
      minZoom: 0.04,
      maxZoom: 4,
      wheelSensitivity: 0.25,
    })
    cyRef.current = cy
    setCyReady(cy)

    cy.on('tap', 'node', (evt) => {
      propsRef.current.onNodeSelect(evt.target.id())
    })
    // Cytoscape has no `tappout`; a tap whose target is the core itself is
    // the background click.
    cy.on('tap', (evt) => {
      if (evt.target === cy) propsRef.current.onNodeSelect(null)
    })
    cy.on('mouseover', 'node', (evt) => propsRef.current.onNodeHover(evt.target.id()))
    cy.on('mouseout', 'node', () => propsRef.current.onNodeHover(null))

    return () => {
      cy.destroy()
      cyRef.current = null
      setCyReady(null)
      stopFlow()
    }
  }, [])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().remove()
    cy.add(props.elements)
    const chosen = props.layout
    cy.layout({ name: chosen, animate: false }).run()
    startFlow(cy, null)
  }, [props.elements, props.layout])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().removeClass('faded')
    cy.elements().removeClass('in out selected')
    if (props.selectedNodeId) {
      const ele = cy.$id(props.selectedNodeId)
      if (!ele.empty()) {
        ele.addClass('selected')
        const nbr = ele.neighborhood().union(ele)
        cy.elements().not(nbr).addClass('faded')
        ele.outgoers('edge').addClass('out')
        ele.incomers('edge').addClass('in')
      }
    }
  }, [props.selectedNodeId, props.elements])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    const cb = (evt: EventObject): void => {
      const id = (evt.target as NodeSingular).id()
      startFlow(cy, id)
    }
    cy.on('mouseover', 'node', cb)
    cy.on('mouseout', 'node', () => startFlow(cy, null))
    return () => {
      cy.off('mouseover', 'node', cb)
      cy.off('mouseout', 'node')
    }
  }, [])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !props.focusRequest) return
    const ele = cy.$id(props.focusRequest.id)
    if (!ele.empty()) {
      cy.animate({
        fit: { eles: ele, padding: 60 },
        duration: 250,
      })
    }
  }, [props.focusRequest])

  return (
    <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
      <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
      <canvas
        id="flow-canvas"
        style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 5 }}
      />
      {cyReady && <Minimap cy={cyReady} />}
    </div>
  )
}
```

- [x] **Step 5: Verify typecheck + build**

Run: `npm run typecheck` and `npm run build` in `vizui/`
Expected: clean.

- [x] **Step 6: Commit**

```bash
git add vizui/src
git commit -m "feat(viz): cytoscape canvas with flows, labels, minimap, highlight"
```

---

### Task 11: Panels, toolbar, and App composition

**Files:**
- Create: `vizui/src/components/TopBar.tsx`, `vizui/src/components/DetailPanel.tsx`, `vizui/src/components/ImpactPanel.tsx`, `vizui/src/components/highlight.tsx`
- Modify: `vizui/src/App.tsx` (full app: repo picker, fetch flow, search, expand/collapse, panels), `vizui/src/styles.css`

**Interfaces:**
- Consumes: all `api.ts` functions (Task 9), `GraphPayload`, `ImpactPayload`, `FileDetail`.
- Produces: working app interactions wired to GraphCanvas (Task 10).

- [x] **Step 1: Create the code highlighter**

`vizui/src/components/highlight.tsx` (`.tsx` — the module renders JSX spans):

```tsx
import type { ReactNode } from 'react'

const KEYWORDS = new Set([
  'import', 'from', 'def', 'class', 'return', 'if', 'elif', 'else', 'for', 'while',
  'func', 'const', 'let', 'var', 'function', 'export', 'async', 'await', 'type',
  'interface', 'package', 'public', 'private', 'static', 'void', 'int', 'str',
])

export function highlightLine(line: string, lang: string | null): ReactNode[] {
  const parts: ReactNode[] = []
  const re = /(\/\/.*$|#.*$|'[^']*'|"[^"]*"|`[^`]*`|\b[A-Za-z_][A-Za-z0-9_]*\b)/g
  let last = 0
  let m: RegExpExecArray | null
  let k = 0
  while ((m = re.exec(line)) !== null) {
    if (m.index > last) parts.push(line.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('//') || tok.startsWith('#')) {
      parts.push(<span key={k++} style={{ color: '#6a9955' }}>{tok}</span>)
    } else if (tok.startsWith("'") || tok.startsWith('"') || tok.startsWith('`')) {
      parts.push(<span key={k++} style={{ color: '#ce9178' }}>{tok}</span>)
    } else if (KEYWORDS.has(tok)) {
      parts.push(<span key={k++} style={{ color: '#569cd6' }}>{tok}</span>)
    } else {
      parts.push(tok)
    }
    last = m.index + tok.length
  }
  if (last < line.length) parts.push(line.slice(last))
  return parts
}
```

Note: with the `react-jsx` transform, no `import React` is needed.

- [x] **Step 2: Create TopBar**

`vizui/src/components/TopBar.tsx`:

```tsx
import type { RepoInfo } from '../types'

export interface TopBarProps {
  repos: RepoInfo[]
  graphId: string | null
  view: 'overview' | 'full'
  layout: 'fcose' | 'concentric' | 'breadthfirst'
  onRepo: (id: string) => void
  onView: (view: 'overview' | 'full') => void
  onLayout: (l: 'fcose' | 'concentric' | 'breadthfirst') => void
  onSearch: (q: string) => void
}

const LAYOUTS: TopBarProps['layout'][] = ['fcose', 'concentric', 'breadthfirst']

export function TopBar(props: TopBarProps) {
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '8px 14px', borderBottom: '1px solid #2b3441' }}>
      <strong>codegraph-viz</strong>
      <select
        value={props.graphId ?? ''}
        onChange={(e) => props.onRepo(e.target.value)}
        style={{ background: '#1a2029', color: '#e8e8e8', border: '1px solid #39424f', borderRadius: 4, padding: 4 }}
      >
        <option value="" disabled>Select repository…</option>
        {props.repos.map((r) => (
          <option key={r.graph_id} value={r.graph_id}>{r.graph_id}</option>
        ))}
      </select>
      <label style={{ fontSize: 12 }}>
        View{' '}
        <select value={props.view} onChange={(e) => props.onView(e.target.value as 'overview' | 'full')}>
          <option value="overview">Overview (clusters)</option>
          <option value="full">Full</option>
        </select>
      </label>
      <label style={{ fontSize: 12 }}>
        Layout{' '}
        <select value={props.layout} onChange={(e) => props.onLayout(e.target.value as TopBarProps['layout'])}>
          {LAYOUTS.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
      </label>
      <input
        placeholder="Search files / functions…"
        style={{ flex: 1, maxWidth: 360, background: '#1a2029', color: '#e8e8e8', border: '1px solid #39424f', borderRadius: 4, padding: 4 }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && props.graphId) props.onSearch((e.target as HTMLInputElement).value)
        }}
      />
    </div>
  )
}
```

- [x] **Step 3: Create DetailPanel**

`vizui/src/components/DetailPanel.tsx`:

```tsx
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
              {detail.functions.map((f) => <li key={`${f.qualified_name}:${f.start_line}`}>{f.name} — {f.start_line}–{f.end_line}</li>)}
            </ul>
          </section>
          <section>
            <strong>Source</strong>
            <pre style={{ fontSize: 11, background: '#0e1116', padding: 8, borderRadius: 4, overflow: 'auto', maxHeight: 420 }}>
              {detail.content.split('\n').map((line, i) => (
                <div key={`${(detail.start_line ?? 0) + i}`}>
                  <span style={{ color: '#4a545f', display: 'inline-block', width: 34, userSelect: 'none' }}>{detail.start_line + i}</span>
                  {highlightLine(line, detail.language)}
                </div>
              ))}
            </pre>
          </section>
        </>
      )}
    </aside>
  )
}
```

- [x] **Step 4: Create ImpactPanel**

`vizui/src/components/ImpactPanel.tsx`:

```tsx
import type { ImpactPayload } from '../types'

export interface ImpactPanelProps {
  impact: ImpactPayload | null
  loading: boolean
  onClose: () => void
}

export function ImpactPanel({ impact, loading, onClose }: ImpactPanelProps) {
  if (!impact && !loading) return null
  return (
    <aside style={{ width: 320, borderRight: '1px solid #2b3441', overflow: 'auto', background: 'rgba(120,40,40,0.15)', padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong style={{ fontSize: 13 }}>Blast radius: {impact?.seed_path ?? '…'}</strong>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#9aa4b1', cursor: 'pointer' }}>✕</button>
      </div>
      <p style={{ fontSize: 12, color: '#ef9a9a' }}>
        {impact?.callers.length ? `${impact.callers.length} function(s) call in (defined in other files). ` : ''}
        {impact?.truncated ? 'Results truncated at the per-category cap.' : ''}
      </p>
      {impact?.rings.map((ring) => (
        <section key={ring.hop} style={{ fontSize: 12, marginBottom: 8 }}>
          <strong style={{ color: '#ef5350' }}>Hop {ring.hop}</strong>
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {ring.paths.map((p) => <li key={p}>{p}</li>)}
          </ul>
        </section>
      ))}
    </aside>
  )
}
```

- [x] **Step 5: Compose App.tsx (full interaction flow)**

Replace `vizui/src/App.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ElementDefinition } from 'cytoscape'
import { expandDir, fetchFileDetail, fetchGraph, fetchImpact, fetchRepos, fetchSubgraph, search } from './api'
import type { FileDetail, GraphPayload, ImpactPayload, RepoInfo } from './types'
import { toElements } from './graph/toCytoscape'
import { GraphCanvas } from './components/GraphCanvas'
import { TopBar } from './components/TopBar'
import { DetailPanel } from './components/DetailPanel'
import { ImpactPanel } from './components/ImpactPanel'

export function App() {
  const [repos, setRepos] = useState<RepoInfo[]>([])
  const [graphId, setGraphId] = useState<string | null>(null)
  const [view, setView] = useState<'overview' | 'full'>('overview')
  const [layout, setLayout] = useState<'fcose' | 'concentric' | 'breadthfirst'>('fcose')
  const [elements, setElements] = useState<ElementDefinition[]>([])
  const [payload, setPayload] = useState<GraphPayload | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hoverId, setHoverId] = useState<string | null>(null)
  const [detail, setDetail] = useState<FileDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [impact, setImpact] = useState<ImpactPayload | null>(null)
  const [impactLoading, setImpactLoading] = useState(false)
  const [focusRequest, setFocusRequest] = useState<{ id: string; nonce: number } | null>(null)
  const expandedClusters = useRef<Set<string>>(new Set())

  useEffect(() => {
    fetchRepos()
      .then(setRepos)
      .catch((e) => console.error(e))
  }, [])

  const loadGraph = useCallback(
    async (id: string, v: 'overview' | 'full') => {
      const p = await fetchGraph(id, v)
      expandedClusters.current = new Set()
      setPayload(p)
      setElements(toElements(p))
      setSelectedId(null)
      setDetail(null)
      setImpact(null)
    },
    [],
  )

  const onRepo = useCallback(
    (id: string) => {
      setGraphId(id)
      setView('overview')
      loadGraph(id, 'overview')
    },
    [loadGraph],
  )

  const onView = useCallback(
    (v: 'overview' | 'full') => {
      setView(v)
      if (graphId) loadGraph(graphId, v)
    },
    [graphId, loadGraph],
  )

  const onNodeSelect = useCallback(
    async (id: string | null) => {
      setSelectedId(id)
      setImpact(null)
      if (!id || !graphId || !payload) return
      const node = payload.nodes.find((n) => n.id === id)
      if (!node) return
      if (node.kind === 'file' && node.path) {
        setDetailLoading(true)
        try {
          setDetail(await fetchFileDetail(graphId, node.path))
        } catch {
          setDetail(null)
        } finally {
          setDetailLoading(false)
        }
      } else if (node.kind === 'dir_cluster' && node.path) {
        const res = await expandDir(graphId, node.path)
        const next = { ...payload, nodes: [...payload.nodes], edges: [...payload.edges] }
        next.nodes = next.nodes.filter((n) => n.id !== id).concat(res.nodes)
        next.edges = dedupeEdges(next.edges.concat(res.edges))
        expandedClusters.current.add(node.id)
        setPayload(next)
        setElements(toElements(next))
      } else {
        setDetail(null)
      }
    },
    [graphId, payload],
  )

  const onNodeHover = useCallback((id: string | null) => setHoverId(id), [])

  const onRequestImpact = useCallback(async () => {
    if (!graphId || !hoverId || !payload) return
    const node = payload.nodes.find((n) => n.id === hoverId)
    if (!node || !node.path) return
    setImpactLoading(true)
    try {
      setImpact(await fetchImpact({ graph_id: graphId, seed_path: node.path, max_hops: 2 }))
    } finally {
      setImpactLoading(false)
    }
  }, [graphId, hoverId, payload])

  const onSearch = useCallback(
    async (q: string) => {
      if (!graphId) return
      const hits = await search(graphId, q)
      if (hits.length) {
        const id = hits[0].path ? `file:${hits[0].path}` : hits[0].id
        setFocusRequest({ id, nonce: Date.now() })
        setSelectedId(id)
      }
    },
    [graphId],
  )

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <TopBar
        repos={repos}
        graphId={graphId}
        view={view}
        layout={layout}
        onRepo={onRepo}
        onView={onView}
        onLayout={setLayout}
        onSearch={onSearch}
      />
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {impact && <ImpactPanel impact={impact} loading={impactLoading} onClose={() => setImpact(null)} />}
        <div style={{ position: 'relative', flex: 1, display: 'flex', flexDirection: 'column' }}>
          <GraphCanvas
            elements={elements}
            layout={layout}
            selectedNodeId={selectedId}
            onNodeSelect={onNodeSelect}
            onNodeHover={onNodeHover}
            focusRequest={focusRequest}
          />
          {payload && (
            <div style={{ position: 'absolute', left: 12, bottom: 10, fontSize: 12, color: '#9aa4b1', background: 'rgba(16,20,24,0.8)', padding: '4px 8px', borderRadius: 4 }}>
              {payload.stats.file_count} files · {payload.stats.edge_count} edges{payload.stats.truncated ? ' (truncated)' : ''}
              {'   '}
              <button onClick={() => { if (hoverId) onRequestImpact() }}>Impact (hovered node)</button>
            </div>
          )}
        </div>
        <DetailPanel detail={detail} loading={detailLoading} onClose={() => { setDetail(null); setSelectedId(null) }} />
      </div>
    </div>
  )
}

function dedupeEdges(edges: { source: string; target: string }[]): { source: string; target: string }[] {
  const seen = new Set<string>()
  const out: { source: string; target: string }[] = []
  for (const e of edges) {
    const k = `${e.source}>${e.target}`
    if (!seen.has(k)) {
      seen.add(k)
      out.push(e)
    }
  }
  return out
}
```

Note: `dedupeEdges` loses the `type`/`weight` fields — preserve the full `GraphEdge` type by typing the helper as `(edges: GraphPayload['edges'])` and returning `GraphPayload['edges']`:

```ts
function dedupeEdges(edges: GraphPayload['edges']): GraphPayload['edges'] {
  const seen = new Set<string>()
  const out: GraphPayload['edges'] = []
  for (const e of edges) {
    const k = `${e.source}>${e.target}`
    if (!seen.has(k)) {
      seen.add(k)
      out.push(e)
    }
  }
  return out
}
```

Replace the version above accordingly. Also remove the unused `hoverId` from the callback deps if lint complains — keep `hoverId` as the impact trigger per the overlay button.

- [x] **Step 6: Verify**

Run: `npm run typecheck` and `npm run build` in `vizui/`
Expected: both clean. Fix any unused-import errors the TS config flags.

- [x] **Step 7: Commit**

```bash
git add vizui/src vizui/package-lock.json
git commit -m "feat(viz): panels, toolbar, and full app interaction flow"
```

---

### Task 12: Build integration, Makefile, README, docs

**Files:**
- Modify: `Makefile` (add 3 targets + `.PHONY`), `README.md` (add a section), `CONTRIBUTING.md` (mention viz lint/test), `docs/data-flow-explainer.md` (add viz process box) — optional docs, README required

**Interfaces:**
- Consumes: `create_app` static serving of `vizui/dist` (already wired in Task 5).

- [x] **Step 1: Add Makefile targets**

Modify `.PHONY` line and append:

```make
.PHONY: ... viz viz-dev viz-build

viz:            ## run the local web UI (browser graph viewer)
	uv run codegraph viz

# Dev mode is two processes: this runs the API only — run `npm run dev` in
# vizui/ from a second terminal for Vite on :5173 proxying /api.
viz-dev:        ## run the API for dev mode (pair with `npm run dev` in vizui/)
	uv run codegraph viz

viz-build:      ## build the frontend bundle into vizui/dist
	cd vizui && npm run build
```

`viz-dev` note: run `npm run dev` (Vite) in a second terminal — add a comment above the target.

- [x] **Step 2: Update README**

Add a "## Local Web UI (`codegraph viz`)" section describing: prerequisites (Neo4j up via `make up`, a repo ingested via `codegraph ingest`, frontend built via `make viz-build`), then `make viz` → open `http://127.0.0.1:8787`. Dev flow: `make viz-dev` (+ `npm run dev` in `vizui/`) with Vite on `:5173` proxying `/api`. Mention the features (overview clusters, search, neighborhood highlight, impact view, detail panel with source).

- [x] **Step 3: Update CONTRIBUTING + data-flow explainer**

- `CONTRIBUTING.md`: add "`make viz-build` + `make viz` are non-MCP features; `ruff`/`mypy` cover `src/codegraph/viz` and Vitest tests live under `vizui/src/**/*.test.ts`."
- `docs/data-flow-explainer.md`: add one line in the app map: `codegraph serve` = MCP stdio; `codegraph viz` = separate browser process (no protocol channel).

- [x] **Step 4: Full validation**

Run: `make lint`
Run: `make typecheck`
Run: `uv run pytest -m "not slow and not integration" -q`
Run: `cd vizui && npm run build && npm test`
Expected: all green.

- [x] **Step 5: Commit**

```bash
git add Makefile README.md CONTRIBUTING.md docs/data-flow-explainer.md
git commit -m "docs(viz): Makefile targets, README, and data-flow note"
```

---

### Task 13: Manual smoke test of the running app

**Files:** none (verification + fix only).

- [x] **Step 1: Boot the stack**

Run: `make up` (Neo4j), `make viz-build`, then `make viz`.
Open `http://127.0.0.1:8787` in a browser.

- [x] **Step 2: Verify happy path**

1. Repo dropdown lists ingested repos (e.g. `github.com/Ritesh-977/KampusCart` if present).
2. Overview shows dir-cluster nodes; click `file:` node → detail panel opens with source.
3. Select a node → neighbors highlight blue/red with arrows.
4. Hover a node → particles flow along its edges.
5. Impact button → blast-radius panel appears.
6. View → Full shows all files; layout switcher changes layout.
7. Search jumps/focuses the match.

- [x] **Step 3: Verify error path**

Stop Neo4j (`make down`), refresh → API returns the JSON hint ("run `make up`"), no stack trace in browser. Restart Neo4j.

- [x] **Step 4: Close out**

Fix any issues found as follow-up commits (`git commit -m "fix(viz): ..."`).
Final gate: `make lint typecheck test` green.

---

## Execution notes (post-implementation)

Corrections made while executing this plan, all verified by tests:

1. **`graph_id` cannot be a URL path segment.** Real slugs are
   `github.com/owner/name` — two slashes — and the ASGI server percent-decodes
   the path before routing, so `%2F` does not help. `/api/graph`, `/api/expand`
   and `/api/file` take `graph_id` (and `path`) as query parameters.
2. **`full_graph` now truncates rather than only flagging.** `_load_full` does
   the uncapped read; `full_graph` caps edges and drops orphaned symbols;
   `overview_graph` clusters the uncapped data.
3. **`expand_dir` returns one level**, not every descendant: files directly in
   the directory plus child `dir_cluster` nodes.
4. **Only file nodes cluster.** A symbol's label is an import specifier
   (`@react-oauth/google`, `../utils`); clustering those invented `dir:@react-oauth`
   and `dir:..` nodes in the real repo's overview. Caught by smoke test.
5. **cytoscape 3.34 ships its own typings.** `Stylesheet` is now
   `StylesheetJson`, there is no `SingularElement`, no `EdgeSingular.otherNode`,
   and `Css.Core` is not partial. `@types/cytoscape` was removed; a small
   `declare module 'cytoscape-fcose'` shim was added.
6. **Frontend fixes:** style selectors must be `node-<kind>` (matching
   `toCytoscape`); `tappout` is not a cytoscape event; the flow canvas needs its
   bitmap synced to its CSS size and positions re-read per frame; the minimap
   needs cytoscape in state, not just a ref.
7. **Test bugs in the plan itself:** the clustering test asserted id-sorted
   output the implementation did not produce; the cytoscape mapping test
   filtered nodes by an `id` prefix that edge ids share; the integration seed
   Cypher (`CREATE ..., MERGE ...`) did not parse; a CLI test used `_cmd_viz`
   without importing it; `impact()` had an unused `externals` variable that
   fails `ruff`.

Verified against the live graph (`github.com/Ritesh-977/KampusCart`, 121 files):
overview returns `dir:client` + `dir:server`, expand returns one level, file
detail returns real source with imports/dependents/functions, impact returns
30 files at hop 1 and 11 at hop 2, and error paths return `{detail, hint}` with
no traceback.
