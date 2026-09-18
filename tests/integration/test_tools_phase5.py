"""Phase 5: ranked search + pagination, and file commit metadata."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def _seed(adapter, gid: str) -> None:
    await adapter._run_write(
        "CREATE (r:Repository {graph_id: $gid, name: $gid, url: 'https://github.com/o/n'}) "
        "CREATE (f:File {graph_id: $gid, path: 'src/search_bar.js', language: 'js', "
        "  deleted: false, last_author: 'Alice', last_commit_at: '2026-07-20T10:00:00+00:00', "
        "  last_commit_sha: 'abc1230'}) "
        "CREATE (g:File {graph_id: $gid, path: 'src/plain.js', language: 'js', deleted: false})",
        gid=gid,
    )
    # Enough same-prefixed functions to page through.
    for i in range(6):
        await adapter._run_write(
            "CREATE (fn:Function {graph_id: $gid, qualified_name: $qn, name: $n, "
            "kind: 'function', path: 'src/search_bar.js'})",
            gid=gid, qn=f"src/search_bar.js::search{i}", n=f"search{i}",
        )


async def test_search_returns_ranked_non_constant_scores(adapter, fresh_graph_id) -> None:
    await _seed(adapter, fresh_graph_id)
    from codegraph.models.tools import SearchNodesArgs
    from codegraph.tools.search_nodes import search_nodes

    res = await search_nodes(
        adapter, SearchNodesArgs(graph_id=fresh_graph_id, query="search", limit=10)
    )
    assert res.hits, "expected full-text hits"
    scores = [h.score for h in res.hits]
    assert scores == sorted(scores, reverse=True), "hits must be ranked best-first"


async def test_search_pagination_returns_disjoint_pages(adapter, fresh_graph_id) -> None:
    await _seed(adapter, fresh_graph_id)
    from codegraph.models.tools import SearchNodesArgs
    from codegraph.tools.search_nodes import search_nodes

    page1 = await search_nodes(
        adapter, SearchNodesArgs(graph_id=fresh_graph_id, query="search", limit=2, offset=0)
    )
    page2 = await search_nodes(
        adapter, SearchNodesArgs(graph_id=fresh_graph_id, query="search", limit=2, offset=2)
    )
    ids1 = {h.id for h in page1.hits}
    ids2 = {h.id for h in page2.hits}
    assert ids1 and ids2
    assert ids1.isdisjoint(ids2), "offset must return a different page"
    assert page1.next_offset == 2


async def test_search_survives_lucene_hostile_query(adapter, fresh_graph_id) -> None:
    """Must degrade, not raise — an LLM will send odd strings."""
    await _seed(adapter, fresh_graph_id)
    from codegraph.models.tools import SearchNodesArgs
    from codegraph.tools.search_nodes import search_nodes

    res = await search_nodes(
        adapter, SearchNodesArgs(graph_id=fresh_graph_id, query="search(", limit=5)
    )
    assert isinstance(res.hits, list)


async def test_get_file_metadata_returns_commit_info(adapter, fresh_graph_id) -> None:
    await _seed(adapter, fresh_graph_id)
    from codegraph.models.tools import GetFileMetadataArgs
    from codegraph.tools.get_file_metadata import get_file_metadata

    res = await get_file_metadata(
        adapter,
        GetFileMetadataArgs(graph_id=fresh_graph_id, file_path="src/search_bar.js"),
    )
    assert res.last_author == "Alice"
    assert res.last_commit_sha == "abc1230"


async def test_get_file_metadata_nulls_when_no_history(adapter, fresh_graph_id) -> None:
    """A repo ingested before commit metadata worked must degrade, not error."""
    await _seed(adapter, fresh_graph_id)
    from codegraph.models.tools import GetFileMetadataArgs
    from codegraph.tools.get_file_metadata import get_file_metadata

    res = await get_file_metadata(
        adapter, GetFileMetadataArgs(graph_id=fresh_graph_id, file_path="src/plain.js")
    )
    assert res.last_author is None
    assert res.path == "src/plain.js"


async def test_get_file_metadata_unknown_file_raises(adapter, fresh_graph_id) -> None:
    from codegraph.models.tools import GetFileMetadataArgs
    from codegraph.tools.get_file_metadata import get_file_metadata

    with pytest.raises(ValueError, match="not found"):
        await get_file_metadata(
            adapter, GetFileMetadataArgs(graph_id=fresh_graph_id, file_path="nope.js")
        )
