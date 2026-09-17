"""VizService query layer against a fake graph reader."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from codegraph.viz.models import ImpactRequest, SubgraphRequest
from codegraph.viz.service import VizService


class FakeAdapter:
    """Scripted stand-in for Neo4jAdapter implementing only what VizService uses.

    ``_run_read`` returns the rows of the FIRST dict key that appears in the
    Cypher, so keys must be listed most-specific-first and act as fingerprints
    of the query shape (the distinctive RETURN fragment, since `MATCH (f:File`
    is shared by half the queries).
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


def _fake() -> FakeAdapter:
    # Keys are checked in order; each must be a substring unique to one query
    # shape (prefer the distinctive RETURN fragment), most-specific first.
    return FakeAdapter({
        "RETURN DISTINCT s.name": _SYMS,
        "RETURN a.path AS src, s.name AS name": _FS_EDGES,
        "RETURN a.path AS src, b.path AS dst": _FF_EDGES,
        "AS chain": _CHAIN_IN + _CHAIN_OUT,
        "f.path IN $paths": _FILES,
        "RETURN fn.name AS name": _FNS,
        "RETURN elementId(f) AS id, f.path AS path": _FILES,
    })


def _svc() -> VizService:
    return VizService(_fake(), Path(tempfile.mkdtemp()))


def test_full_graph() -> None:
    out = asyncio.run(_svc().full_graph("o/n"))
    assert out.view == "full"
    assert {n.path for n in out.nodes if n.kind == "file"} >= {"auth.py", "api.py", "db.py"}
    assert any(n.kind == "symbol" and n.path is None for n in out.nodes)
    assert any(e.type == "IMPORTS" for e in out.edges)
    assert out.stats.file_count == 4
    assert out.stats.truncated is False


def test_full_graph_caps_edges() -> None:
    out = asyncio.run(_svc().full_graph("o/n", max_edges=1))
    assert out.stats.truncated is True
    assert len(out.edges) == 1
    # every file node survives the cap; the payload stays self-consistent
    assert len([n for n in out.nodes if n.kind == "file"]) == 4
    ids = {n.id for n in out.nodes}
    assert all(e.source in ids and e.target in ids for e in out.edges)


def test_overview_clusters() -> None:
    out = asyncio.run(_svc().overview_graph("o/n"))
    assert any(n.kind == "dir_cluster" and n.id == "dir:lib" for n in out.nodes)


def test_expand_dir_returns_one_level() -> None:
    out = asyncio.run(_svc().expand_dir("o/n", "lib"))
    assert {n.id for n in out.nodes} == {"file:lib/util.py"}
    assert out.dir_prefix == "lib"


def test_subgraph_builds_edges_from_chains() -> None:
    out = asyncio.run(_svc().subgraph(SubgraphRequest(graph_id="o/n", seed_path="auth.py")))
    assert any(e.source == "file:api.py" and e.target == "file:auth.py" for e in out.edges)
    assert any(e.source == "file:auth.py" and e.target == "file:db.py" for e in out.edges)
    assert any(e.target == "sym:os" for e in out.edges)


def test_impact_rings() -> None:
    out = asyncio.run(_svc().impact(ImpactRequest(graph_id="o/n", seed_path="auth.py", max_hops=2)))
    assert out.rings and out.rings[0].hop == 1
    assert "api.py" in out.rings[0].paths
    assert "db.py" in out.rings[0].paths
    assert out.callers == []
    assert out.calls == []


def test_file_detail_missing_file_raises() -> None:
    with pytest.raises(ValueError):
        asyncio.run(_svc().file_detail("o/n", "nonexistent.py"))
