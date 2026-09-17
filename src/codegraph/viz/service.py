"""VizService — read-only query layer backing the codegraph-viz REST API.

All Cypher lives here (parameterized, ``graph_id``-scoped) on top of the
existing Neo4jAdapter's ``_run_read`` helper. Variable-length relationship
bounds are the single allowed literal interpolation, validated before use
(mirrors ``_validated_hop_bound`` in the adapter).
"""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise
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
    """Validate a hop/depth bound before splicing it into a Cypher pattern."""
    if (
        not isinstance(depth, int)
        or isinstance(depth, bool)
        or not (0 <= depth <= MAX_TRAVERSAL_HOPS)
    ):
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

        Split out of ``full_graph`` so ``overview_graph`` can cluster the whole
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
            # Actually cap the payload, don't just flag it: a 5k-file repo
            # carries ~20k edges and the browser has to lay out every one of
            # them. File nodes stay (they are the repo's inventory); symbols
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
            for src, tgt in pairwise(chain):
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
            symbols.extend(
                GraphEdge(
                    source=f"file:{req.seed_path}", target=f"sym:{row['name']}", type="IMPORTS"
                )
                for row in syms
            )

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
            name = e.target.split(":", 1)[1]
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
            graph_id=req.graph_id, file_path=req.seed_path, direction="both",
            max_hops=req.max_hops,
        )
        by_hop: dict[int, set[str]] = defaultdict(set)
        for entry in res["imported_by"] + res["imports"]:
            by_hop[entry["hop"]].add(entry["path"])
        rings = [ImpactRing(hop=h, paths=sorted(by_hop[h])) for h in sorted(by_hop)]
        # `callers`/`calls` carry function qualified_names, not file paths —
        # the adapter reuses the "path" key for both.
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

    async def search(
        self, graph_id: str, q: str, kind: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        return await self._adapter.search_nodes(
            graph_id=graph_id, query=q, kind=kind, limit=limit
        )

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
