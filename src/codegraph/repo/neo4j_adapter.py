"""Neo4j-backed CodeGraphRepository. Sync driver wrapped with asyncio.to_thread.

Mirrors the proven pattern from the sibling kg-mcp: every Cypher statement is
parameterized and filters on graph_id. The one exception is
`_validated_hop_bound`, which range-checks `max_hops` and embeds it as a
literal in a variable-length relationship pattern, since Neo4j cannot
parameterize the bounds of `[*1..n]`. All read methods below are implemented.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from neo4j import Driver, GraphDatabase

from codegraph.config import Settings
from codegraph.models.common import MAX_TRAVERSAL_HOPS
from codegraph.repo.migrations import build_migration_cypher

# Default per-category cap on find_file_dependencies result lists; `truncated`
# is set if any category hits it. Overridable per-adapter via Settings.
_DEFAULT_MAX_DEP_RESULTS = 500


def _validated_hop_bound(max_hops: int) -> int:
    """Range-check max_hops for embedding as a Cypher literal.

    Neo4j cannot parameterize the bounds of a variable-length relationship
    pattern (`[:IMPORTS*1..$max_hops]` is a syntax error), so the bound must
    be embedded as literal query text instead of a parameter. The pydantic
    layer already bounds `max_hops`, but this Protocol method is reachable
    directly, so it gets its own defense before the value is spliced into
    query text. Both bounds come from MAX_TRAVERSAL_HOPS so they can't drift.
    """
    if (
        not isinstance(max_hops, int)
        or isinstance(max_hops, bool)
        or not (0 <= max_hops <= MAX_TRAVERSAL_HOPS)
    ):
        raise ValueError(
            f"max_hops must be an int in [0, {MAX_TRAVERSAL_HOPS}], got {max_hops!r}"
        )
    return max_hops


class Neo4jAdapter:
    """Concrete CodeGraphRepository backed by a Neo4j 5.x driver."""

    def __init__(
        self,
        *,
        uri: str,
        user: str,
        password: str,
        db: str,
        max_dep_results: int = _DEFAULT_MAX_DEP_RESULTS,
    ) -> None:
        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        self._db = db
        self._max_dep_results = max(1, max_dep_results)

    @classmethod
    def from_settings(cls, settings: Settings) -> Neo4jAdapter:
        return cls(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            db=settings.neo4j_db,
            max_dep_results=settings.max_dependency_results,
        )

    async def connect(self) -> None:
        await asyncio.to_thread(self._driver.verify_connectivity)

    async def close(self) -> None:
        await asyncio.to_thread(self._driver.close)

    async def apply_migrations(self) -> None:
        for stmt in build_migration_cypher():
            await self._run_write(stmt)

    # --- read methods (implemented now) ---

    async def list_repos(self) -> list[dict[str, Any]]:
        # Deliberately unfiltered by graph_id — this is the "what repos exist?"
        # entry point. Degrade gracefully rather than failing the whole listing
        # on one malformed node: skip rows with no graph_id (unaddressable
        # anyway) and coalesce a missing name/url instead of returning nulls
        # that would blow up RepoInfo validation for every other repo too.
        rows = await self._run_read(
            "MATCH (r:Repository) WHERE r.graph_id IS NOT NULL "
            "RETURN r.graph_id AS graph_id, coalesce(r.name, r.graph_id) AS name, "
            "       coalesce(r.url, '') AS url, "
            "       r.default_branch AS default_branch, r.ingested_at AS ingested_at, "
            "       coalesce(r.ingest_status, 'complete') AS ingest_status"
        )
        return [_normalize_repo_row(r) for r in rows]

    async def get_repo_info(self, *, graph_id: str) -> dict[str, Any] | None:
        rows = await self._run_read(
            "MATCH (r:Repository {graph_id: $gid}) "
            "OPTIONAL MATCH (f:File {graph_id: $gid}) WHERE f.deleted = false "
            "OPTIONAL MATCH (fn:Function {graph_id: $gid})<-[:DEFINES]-(fnFile:File {graph_id: $gid}) "
            "WHERE fnFile.deleted = false "
            "RETURN r.graph_id AS graph_id, r.name AS name, r.url AS url, "
            "       r.default_branch AS default_branch, r.ingested_at AS ingested_at, "
            "       coalesce(r.ingest_status, 'complete') AS ingest_status, "
            "       count(DISTINCT f) AS file_count, count(DISTINCT fn) AS function_count",
            gid=graph_id,
        )
        if not rows or rows[0].get("graph_id") is None:
            return None
        return _normalize_repo_row(rows[0])

    # --- read methods implemented in Day 4/5 ---

    async def get_file_info(
        self, *, graph_id: str, file_path: str
    ) -> dict[str, Any] | None:
        rows = await self._run_read(
            "MATCH (f:File {graph_id: $gid, path: $p}) WHERE f.deleted = false "
            "RETURN f.path AS path, f.language AS language, "
            "       f.last_author AS last_author, f.last_commit_at AS last_commit_at, "
            "       f.last_commit_sha AS last_commit_sha",
            gid=graph_id, p=file_path,
        )
        if not rows:
            return None
        row = rows[0]
        # Commit fields stay nullable: a repo ingested before commit metadata
        # worked (or a file with no history) must degrade to null, not error.
        return {
            "path": row["path"],
            "language": row["language"],
            "last_author": row.get("last_author"),
            "last_commit_at": _as_iso(row.get("last_commit_at")),
            "last_commit_sha": row.get("last_commit_sha"),
        }

    async def get_repo_structure(
        self, *, graph_id: str, path: str, limit: int
    ) -> dict[str, Any]:
        prefix = (path + "/") if path else ""
        rows = await self._run_read(
            "MATCH (f:File {graph_id: $gid}) "
            "WHERE f.deleted = false AND ($prefix = '' OR f.path STARTS WITH $prefix) "
            "RETURN f.path AS p, f.language AS lang "
            "ORDER BY f.path LIMIT $lim",
            gid=graph_id, prefix=prefix, lim=limit + 1,
        )
        entries: list[dict[str, Any]] = []
        seen_dirs: set[str] = set()
        for r in rows:
            rel = r["p"][len(prefix):] if prefix else r["p"]
            parts = rel.split("/")
            if len(parts) == 1:
                entries.append({"name": parts[0], "type": "file", "language": r["lang"]})
            else:
                d = parts[0]
                if d not in seen_dirs:
                    seen_dirs.add(d)
                    entries.append({"name": d, "type": "dir"})
        truncated = len(rows) > limit
        return {"path": path, "entries": entries[:limit], "truncated": truncated}

    async def find_file_dependencies(
        self, *, graph_id: str, file_path: str, direction: str, max_hops: int
    ) -> dict[str, Any]:
        hops = _validated_hop_bound(max_hops)
        run_hops = hops >= 1
        cap = self._max_dep_results
        lim = cap + 1

        # imported_by: files that transitively IMPORT this file (chains of
        # File-IMPORTS->File up to `hops` deep). Dedup via min(length(path))
        # since diamond/cycle shapes can reach the same file via multiple
        # path lengths.
        imported_by = await self._run_read(
            "MATCH (tgt:File {graph_id: $gid, path: $p}) "
            f"MATCH path = (src:File {{graph_id: $gid}})-[:IMPORTS*1..{hops}]->(tgt) "
            "WHERE ALL(n IN nodes(path)[0..-1] WHERE n:File AND n.deleted = false) "
            "WITH src, min(length(path)) AS hop "
            "RETURN src.path AS path, 'file' AS kind, 'imported_by' AS via, hop "
            "ORDER BY hop, path LIMIT $lim",
            gid=graph_id, p=file_path, lim=lim,
        ) if run_hops and direction in ("imported_by", "both") else []

        # imports: files transitively IMPORTed by this file
        imports = await self._run_read(
            "MATCH (src:File {graph_id: $gid, path: $p}) "
            f"MATCH path = (src)-[:IMPORTS*1..{hops}]->(tgt:File {{graph_id: $gid}}) "
            "WHERE ALL(n IN nodes(path)[1..] WHERE n:File AND n.deleted = false) "
            "WITH tgt, min(length(path)) AS hop "
            "RETURN tgt.path AS path, 'file' AS kind, 'imports' AS via, hop "
            "ORDER BY hop, path LIMIT $lim",
            gid=graph_id, p=file_path, lim=lim,
        ) if run_hops and direction in ("imports", "both") else []

        # callers: functions that transitively CALL into a function defined in
        # this file. Two MATCH clauses keep `hop` as pure CALLS-chain depth,
        # not inflated by the anchoring DEFINES edge. Intermediate Function
        # nodes aren't deleted-checked (Function has no `deleted` property of
        # its own; only its defining File does) — accepted gap, not fixed here.
        callers = await self._run_read(
            "MATCH (calleeFile:File {graph_id: $gid, path: $p})-[:DEFINES]->(callee:Function {graph_id: $gid}) "
            "WHERE calleeFile.deleted = false "
            f"MATCH path = (caller:Function {{graph_id: $gid}})-[:CALLS*1..{hops}]->(callee) "
            "WITH caller, min(length(path)) AS hop "
            "RETURN caller.qualified_name AS path, 'function' AS kind, 'called_by' AS via, hop "
            "ORDER BY hop, path LIMIT $lim",
            gid=graph_id, p=file_path, lim=lim,
        ) if run_hops and direction in ("imported_by", "both") else []

        # calls: functions transitively CALLed by this file's functions
        calls = await self._run_read(
            "MATCH (callerFile:File {graph_id: $gid, path: $p})-[:DEFINES]->(caller:Function {graph_id: $gid}) "
            "WHERE callerFile.deleted = false "
            f"MATCH path = (caller)-[:CALLS*1..{hops}]->(callee:Function {{graph_id: $gid}}) "
            "WITH callee, min(length(path)) AS hop "
            "RETURN callee.qualified_name AS path, 'function' AS kind, 'calls' AS via, hop "
            "ORDER BY hop, path LIMIT $lim",
            gid=graph_id, p=file_path, lim=lim,
        ) if run_hops and direction in ("imports", "both") else []

        # external symbols (unresolved imports from File + unresolved calls from
        # Function) — inherently single-hop, unresolved-symbol lookups, not
        # part of the hop-depth expansion above, but both are outgoing from
        # this file's perspective, so gated the same as imports/calls.
        ext_imports = await self._run_read(
            "MATCH (f:File {graph_id: $gid, path: $p})-[:IMPORTS]->(s:Symbol {graph_id: $gid}) "
            "WHERE f.deleted = false "
            "RETURN s.name AS name, s.kind AS kind",
            gid=graph_id, p=file_path,
        ) if direction in ("imports", "both") else []
        ext_calls = await self._run_read(
            "MATCH (f:File {graph_id: $gid, path: $p})-[:DEFINES]->(fn:Function {graph_id: $gid})"
            "-[:CALLS]->(s:Symbol {graph_id: $gid}) "
            "WHERE f.deleted = false "
            "RETURN s.name AS name, s.kind AS kind",
            gid=graph_id, p=file_path,
        ) if direction in ("imports", "both") else []
        ext = ext_imports + ext_calls

        truncated = any(
            len(rows) > cap for rows in (imported_by, imports, callers, calls)
        )

        return {
            "file": {"path": file_path, "graph_id": graph_id},
            "imported_by": imported_by[:cap],
            "imports": imports[:cap],
            "callers": callers[:cap],
            "calls": calls[:cap],
            "external_symbols": ext,
            "truncated": truncated,
            "hint": (
                f"results truncated at {cap} per category; narrow direction or max_hops"
                if truncated
                else None
            ),
        }

    async def search_nodes(
        self, *, graph_id: str, query: str, kind: str, limit: int, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Ranked search, falling back to substring matching.

        The full-text index gives real relevance scores, but its Lucene parser
        rejects some inputs an LLM will plausibly send (a bare `~`, unbalanced
        quotes). A search tool that raises on odd input is worse than one that
        quietly degrades, so any failure falls through to the CONTAINS path.
        """
        try:
            hits = await self._search_fulltext(
                graph_id=graph_id, query=query, kind=kind, limit=limit, offset=offset
            )
            if hits:
                return hits
        except Exception:
            pass  # index missing or query unparseable — use substring matching
        return await self._search_substring(
            graph_id=graph_id, query=query, kind=kind, limit=limit, offset=offset
        )

    async def _search_fulltext(
        self, *, graph_id: str, query: str, kind: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        indexes = {"function": ("function_fulltext",), "file": ("file_fulltext",)}.get(
            kind, ("function_fulltext", "file_fulltext")
        )
        out: list[dict[str, Any]] = []
        for index in indexes:
            rows = await self._run_read(
                f"CALL db.index.fulltext.queryNodes('{index}', $q) YIELD node, score "
                "WHERE node.graph_id = $gid AND (NOT node:File OR node.deleted = false) "
                "RETURN elementId(node) AS id, "
                "coalesce(node.qualified_name, '') AS qualified_name, "
                "coalesce(node.name, node.path) AS name, "
                "CASE WHEN node:Function THEN 'function' WHEN node:File THEN 'file' "
                "     ELSE 'other' END AS kind, "
                "coalesce(node.path, '') AS path, score "
                "ORDER BY score DESC, name",
                gid=graph_id, q=_fulltext_query(query),
            )
            out.extend(rows)
        out.sort(key=lambda r: (-float(r["score"]), str(r["name"])))
        return out[offset : offset + limit]

    async def _search_substring(
        self, *, graph_id: str, query: str, kind: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        q = query.lower()
        # Fetch offset+limit then slice, since SKIP/LIMIT params complicate the
        # three query shapes below for no benefit at these result sizes.
        lim = offset + limit
        if kind == "function":
            cypher = (
                "MATCH (fn:Function {graph_id: $gid}) WHERE toLower(fn.name) CONTAINS $q "
                "RETURN elementId(fn) AS id, fn.qualified_name AS qualified_name, "
                "fn.name AS name, fn.kind AS kind, '' AS path, 1.0 AS score "
                "LIMIT $lim"
            )
        elif kind == "file":
            cypher = (
                "MATCH (f:File {graph_id: $gid}) WHERE f.deleted = false AND toLower(f.path) CONTAINS $q "
                "RETURN elementId(f) AS id, '' AS qualified_name, "
                "f.path AS name, 'file' AS kind, f.path AS path, 1.0 AS score "
                "LIMIT $lim"
            )
        else:
            cypher = (
                "MATCH (n {graph_id: $gid}) WHERE "
                "(n:Function AND toLower(n.name) CONTAINS $q) "
                "OR (n:File AND n.deleted = false AND toLower(n.path) CONTAINS $q) "
                "RETURN elementId(n) AS id, "
                "coalesce(n.qualified_name, '') AS qualified_name, "
                "coalesce(n.name, n.path) AS name, "
                "CASE WHEN n:Function THEN 'function' WHEN n:File THEN 'file' ELSE 'other' END AS kind, "
                "coalesce(n.path, '') AS path, 1.0 AS score LIMIT $lim"
            )
        rows = await self._run_read(cypher, gid=graph_id, q=q, lim=lim)
        return rows[offset:]

    async def get_node_detail(
        self, *, graph_id: str, node_id: str
    ) -> dict[str, Any] | None:
        rows = await self._run_read(
            "MATCH (n {graph_id: $gid}) WHERE elementId(n) = $nid "
            "OPTIONAL MATCH (n)<-[:DEFINES]-(df:File {graph_id: $gid}) "
            "WITH n, df "
            "WHERE (NOT n:File OR n.deleted = false) "
            "  AND (NOT n:Function OR df IS NULL OR df.deleted = false) "
            "RETURN elementId(n) AS id, coalesce(n.name, n.path) AS name, "
            "CASE WHEN n:Function THEN n.kind WHEN n:File THEN 'file' ELSE 'other' END AS kind, "
            "coalesce(n.path, '') AS path, n.start_line AS sl, n.end_line AS el",
            gid=graph_id, nid=node_id,
        )
        if not rows:
            return None
        return {
            "id": rows[0]["id"],
            "name": rows[0]["name"],
            "kind": rows[0]["kind"],
            "path": rows[0]["path"] or None,
            "start_line": rows[0].get("sl"),
            "end_line": rows[0].get("el"),
        }

    # --- low-level exec used by graph_builder + tests ---

    async def _run_read(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._exec_read, cypher, params)

    async def _run_write(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._exec_write, cypher, params)

    async def _run_write_batch(
        self, statements: list[tuple[str, dict[str, Any]]]
    ) -> list[list[dict[str, Any]]]:
        """Run multiple write statements in a single transaction (one commit
        per batch instead of one per statement) — used by ingest batching."""
        return await asyncio.to_thread(self._exec_write_batch, statements)

    def _exec_read(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self._driver.session(database=self._db) as session:
            return session.execute_read(lambda tx: tx.run(cypher, params).data())

    def _exec_write(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self._driver.session(database=self._db) as session:
            return session.execute_write(lambda tx: tx.run(cypher, params).data())

    def _exec_write_batch(
        self, statements: list[tuple[str, dict[str, Any]]]
    ) -> list[list[dict[str, Any]]]:
        def _tx(tx: Any) -> list[list[dict[str, Any]]]:
            return [tx.run(cypher, params).data() for cypher, params in statements]

        with self._driver.session(database=self._db) as session:
            return session.execute_write(_tx)

    async def soft_cleanup(self, graph_id: str) -> None:
        """Test/dev helper: remove all nodes/rels for a graph_id namespace."""
        await self._run_write(
            "MATCH (n {graph_id: $gid}) DETACH DELETE n", gid=graph_id
        )


def _fulltext_query(query: str) -> str:
    """Turn a plain user query into a safe Lucene prefix query.

    Special characters are escaped so a query like `foo(` can't blow up the
    parser, and a trailing `*` makes partial names match the way users expect
    from the old substring behaviour.
    """
    escaped = re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", query.strip())
    if not escaped:
        return "*"
    terms = [f"{t}*" for t in escaped.split() if t]
    return " ".join(terms) if terms else "*"


def _as_iso(value: Any) -> str | None:
    """Neo4j temporals -> ISO string; pass through str/None untouched."""
    if value is None or isinstance(value, str):
        return value
    to_native = getattr(value, "to_native", None)
    if callable(to_native):
        return str(to_native().isoformat())
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _normalize_repo_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert Neo4j temporal types to JSON-safe strings."""
    out = dict(row)
    ts = out.get("ingested_at")
    if ts is not None and not isinstance(ts, str):
        # Neo4j returns datetime objects — convert to ISO string for pydantic
        to_native = getattr(ts, "to_native", None)
        if callable(to_native):
            out["ingested_at"] = to_native().isoformat()
        elif hasattr(ts, "isoformat"):
            out["ingested_at"] = ts.isoformat()
        else:
            out["ingested_at"] = str(ts)
    return out
