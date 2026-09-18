"""viz service + REST endpoints against a live Neo4j (testcontainers)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.viz.models import ImpactRequest, SubgraphRequest
from codegraph.viz.service import VizService

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
    svc = VizService(adapter, Path("./repos"))
    out = await svc.full_graph(fresh_graph_id)
    paths = {n.path for n in out.nodes if n.kind == "file"}
    assert {"auth.py", "api.py", "src/util.py"} <= paths
    assert any(n.kind == "symbol" and n.label == "os" for n in out.nodes)
    assert any(e.source == "file:api.py" and e.target == "file:auth.py" for e in out.edges)
    assert any(e.source == "file:auth.py" and e.target == "sym:os" for e in out.edges)


async def test_viz_overview_clusters(adapter, fresh_graph_id) -> None:
    await _seed(adapter, fresh_graph_id)
    svc = VizService(adapter, Path("./repos"))
    out = await svc.overview_graph(fresh_graph_id, depth=1)
    clusters = {n.id for n in out.nodes if n.kind == "dir_cluster"}
    assert "dir:src" in clusters


async def test_viz_expand_dir(adapter, fresh_graph_id) -> None:
    await _seed(adapter, fresh_graph_id)
    svc = VizService(adapter, Path("./repos"))
    out = await svc.expand_dir(fresh_graph_id, "src")
    assert {n.id for n in out.nodes} == {"file:src/util.py"}


async def test_viz_subgraph_and_impact(adapter, fresh_graph_id) -> None:
    await _seed(adapter, fresh_graph_id)
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


async def test_viz_file_detail_missing_file_is_valueerror(adapter, fresh_graph_id) -> None:
    await _seed(adapter, fresh_graph_id)
    svc = VizService(adapter, Path("./repos"))
    with pytest.raises(ValueError):
        await svc.file_detail(fresh_graph_id, "does/not/exist.py")
