"""FastAPI app endpoints for codegraph-viz (offline, fake adapter)."""

from __future__ import annotations

import tempfile
from pathlib import Path

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
        if "f.path IN $paths" in cypher:
            return [{"path": "auth.py", "language": "python"},
                    {"path": "api.py", "language": "python"}]
        if "RETURN a.path AS src, s.name AS name" in cypher:
            return [{"src": "api.py", "name": "os"}]
        if "a.path AS src, b.path AS dst" in cypher:
            return [{"src": "api.py", "dst": "auth.py"}]
        if "MATCH (f:File" in cypher:
            return [{"id": "n1", "path": "auth.py", "language": "python"},
                    {"id": "n2", "path": "api.py", "language": "python"}]
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


def test_graph_id_with_slashes_round_trips(client) -> None:
    # Real graph_ids look like `github.com/owner/name` — two slashes. This is
    # why graph_id is a query param and never a path segment.
    r = client.get("/api/graph", params={"graph_id": "github.com/o/n", "view": "overview"})
    assert r.status_code == 200
    assert r.json()["graph_id"] == "github.com/o/n"


def test_subgraph_endpoint(client) -> None:
    r = client.post("/api/subgraph", json={"graph_id": "o/n", "seed_path": "auth.py", "depth": 2})
    assert r.status_code == 200
    assert any(e["source"] == "file:api.py" for e in r.json()["edges"])


def test_impact_endpoint(client) -> None:
    r = client.post("/api/impact", json={"graph_id": "o/n", "seed_path": "auth.py", "max_hops": 2})
    assert r.status_code == 200
    assert r.json()["seed_path"] == "auth.py"


def test_bad_request_body_is_422_with_hint(client) -> None:
    r = client.post("/api/impact", json={"graph_id": "o/n", "seed_path": "a.py", "max_hops": 0})
    assert r.status_code == 422
    assert "hint" in r.json()


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


def test_file_detail_missing_is_404_with_hint() -> None:
    class Boom(FakeAdapter):
        async def get_file_info(self, *, graph_id: str, file_path: str):
            return None

    app = create_app(Settings(repos_dir=Path(tempfile.mkdtemp()), viz_port=8787), adapter=Boom())
    with TestClient(app) as c:
        r = c.get("/api/file", params={"graph_id": "o/n", "path": "nope.py"})
    assert r.status_code == 404
    assert "hint" in r.json()


def test_unknown_route_is_404(client) -> None:
    r = client.get("/api/doesnotexist")
    assert r.status_code == 404


def test_db_failure_is_500_with_hint_and_no_stack_trace() -> None:
    """Neo4j being down must read as guidance, not a traceback."""

    class Down(FakeAdapter):
        async def list_repos(self):
            raise ConnectionError("Unable to retrieve routing information")

    app = create_app(Settings(repos_dir=Path(tempfile.mkdtemp())), adapter=Down())
    # raise_server_exceptions=False: Starlette's ServerErrorMiddleware sends the
    # handler's response and then re-raises, which the test client would
    # otherwise surface instead of the response a browser gets.
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/repos")
    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == "internal error"
    assert "make up" in body["hint"]
    assert "Traceback" not in r.text


def test_findings_endpoint(client) -> None:
    r = client.get("/api/findings", params={"graph_id": "o/n"})
    assert r.status_code == 200
    body = r.json()
    assert body["file_count"] == 2
    assert "hubs" in body and "orphans" in body and "cycles" in body
    assert body["coupling_available"] is False
    assert body["coupling_hint"]
