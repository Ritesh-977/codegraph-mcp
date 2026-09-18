"""list_repos tool integration test."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_list_repos_returns_ingested(adapter, fresh_graph_id) -> None:
    await adapter._run_write(
        "CREATE (r:Repository {graph_id: $gid, name: $gid, url: $url, default_branch: 'main'})",
        gid=fresh_graph_id, url="https://github.com/test/x",
    )
    from codegraph.tools.list_repos import list_repos

    res = await list_repos(adapter)
    gids = [r.graph_id for r in res.repos]
    assert fresh_graph_id in gids


async def test_list_repos_tolerates_repo_missing_name_and_url(adapter, fresh_graph_id) -> None:
    """One malformed Repository node must not break the whole listing —
    list_repos is unfiltered by graph_id, so a single bad row would otherwise
    take down the LLM's primary discovery tool for every repo."""
    await adapter._run_write(
        "CREATE (r:Repository {graph_id: $gid})", gid=fresh_graph_id
    )
    from codegraph.tools.list_repos import list_repos

    res = await list_repos(adapter)
    hit = next((r for r in res.repos if r.graph_id == fresh_graph_id), None)
    assert hit is not None
    assert hit.name == fresh_graph_id  # falls back to graph_id
    assert hit.url == ""
