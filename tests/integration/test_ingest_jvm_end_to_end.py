"""End-to-end: ingest the Java/Kotlin fixtures, query the graph back."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

_CASES = {
    "java_repo": (
        "src/main/java/com/foo/app/App.java",
        "src/main/java/com/foo/service/UserService.java",
        "src/main/java/com/foo/repo/UserRepo.java",
    ),
    "kotlin_repo": (
        "src/main/kotlin/com/foo/app/App.kt",
        "src/main/kotlin/com/foo/service/UserService.kt",
        "src/main/kotlin/com/foo/repo/UserRepo.kt",
    ),
}


async def _ingest(adapter, graph_id: str, repo: str) -> None:
    from codegraph.ingestion.graph_builder import build_ingest_plan, run_plan
    from codegraph.ingestion.languages import support_for
    from codegraph.ingestion.walker import walk_repo

    entries = walk_repo(_FIXTURES / repo)
    files = []
    for e in entries:
        support = support_for(e.language)
        if support is not None:
            files.append(support.parse(e.path, e.abspath.read_bytes()))
    plan = build_ingest_plan(
        slug=graph_id,
        url=f"https://github.com/test/{repo}",
        branch="main",
        files=files,
        commits={},
        known_paths={f.path for f in files},
    )
    await run_plan(adapter, plan)


@pytest.mark.parametrize("repo", list(_CASES))
async def test_jvm_fixture_writes_file_and_function_nodes(
    adapter, fresh_graph_id, repo: str
) -> None:
    app, service, _ = _CASES[repo]
    await _ingest(adapter, fresh_graph_id, repo)

    rows = await adapter._run_read(
        "MATCH (f:File {graph_id: $gid}) RETURN f.path AS p ORDER BY p", gid=fresh_graph_id
    )
    paths = [r["p"] for r in rows]
    assert app in paths and service in paths

    fns = await adapter._run_read(
        "MATCH (:File {graph_id: $gid})-[:DEFINES]->(fn:Function {graph_id: $gid}) "
        "RETURN count(fn) AS c",
        gid=fresh_graph_id,
    )
    assert fns[0]["c"] > 0


@pytest.mark.parametrize("repo", list(_CASES))
async def test_jvm_imports_become_file_edges_not_symbols(
    adapter, fresh_graph_id, repo: str
) -> None:
    """The resolver must produce File->File edges; all-Symbol means it's broken."""
    app, service, _ = _CASES[repo]
    await _ingest(adapter, fresh_graph_id, repo)

    rows = await adapter._run_read(
        "MATCH (s:File {graph_id: $gid, path: $p})-[:IMPORTS]->(t:File {graph_id: $gid}) "
        "RETURN t.path AS target",
        gid=fresh_graph_id, p=app,
    )
    assert [r["target"] for r in rows] == [service]


@pytest.mark.parametrize("repo", list(_CASES))
async def test_jvm_multi_hop_dependency_traversal(adapter, fresh_graph_id, repo: str) -> None:
    """App -> UserService -> UserRepo, so UserRepo has a 2-hop dependent."""
    app, service, repo_file = _CASES[repo]
    await _ingest(adapter, fresh_graph_id, repo)

    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path=repo_file, direction="imported_by", max_hops=2
        ),
    )
    assert {e.path: e.hop for e in res.imported_by} == {service: 1, app: 2}
