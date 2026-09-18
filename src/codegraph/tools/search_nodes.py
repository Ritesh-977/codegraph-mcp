"""search_nodes tool — find functions/files by name."""

from __future__ import annotations

from codegraph.models.tools import SearchHit, SearchNodesArgs, SearchNodesResult
from codegraph.repo.port import CodeGraphRepository


async def search_nodes(
    repo: CodeGraphRepository, args: SearchNodesArgs
) -> SearchNodesResult:
    rows = await repo.search_nodes(
        graph_id=args.graph_id,
        query=args.query,
        kind=args.kind,
        limit=args.limit,
        offset=args.offset,
    )
    hits = [SearchHit(**r) for r in rows]
    # A full page implies there may be more; the caller pages with this.
    nxt = args.offset + args.limit if len(hits) == args.limit else None
    return SearchNodesResult(hits=hits, next_offset=nxt)
