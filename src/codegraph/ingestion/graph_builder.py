"""Graph builder: turns ExtractedFiles into a list of (Cypher, params) statements.

Two-pass CALLS resolution: defines all :Function nodes first, then resolves
calls against the full known-qualified-name set in a final pass. Unresolved
imports/calls become :Symbol leaves (never phantom File/Function nodes).

Every Cypher statement is parameterized and filters on graph_id.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from codegraph.ingestion.commits import CommitInfo
from codegraph.ingestion.languages import support_for
from codegraph.models.ingestion import ExtractedCall, ExtractedFile


@dataclass
class IngestSummary:
    files: int
    functions: int
    imports: int
    calls: int
    external_symbols: int
    pruned: int


def build_ingest_plan(
    *,
    slug: str,
    url: str,
    branch: str,
    files: list[ExtractedFile],
    commits: dict[str, CommitInfo],
    known_paths: set[str],
) -> list[tuple[str, dict[str, Any]]]:
    """Build the ordered list of (Cypher, params) statements for ingestion."""
    plan: list[tuple[str, dict[str, Any]]] = []

    # 1. Repository node. `ingested_at` is deliberately NOT set here: it used to
    # be stamped in this first statement, so a run that died at 80% still left a
    # Repository claiming a fresh timestamp and list_repos reported a
    # half-written graph as freshly ingested. It is stamped in the final
    # statement instead, once the work has actually landed.
    plan.append((
        "MERGE (r:Repository {graph_id: $gid}) "
        "SET r.name = $name, r.url = $url, r.default_branch = $branch, "
        "    r.ingest_status = 'running'",
        {"gid": slug, "name": slug, "url": url, "branch": branch},
    ))

    # 2. Files + CONTAINS + DEFINES (pass 1)
    for ef in files:
        ci = commits.get(ef.path)
        set_clause = "f.language = $lang, f.deleted = false"
        params: dict[str, Any] = {"gid": slug, "path": ef.path, "lang": ef.language}
        if ci:
            set_clause += ", f.last_author = $author, f.last_commit_at = $date, f.last_commit_sha = $sha"
            params["author"] = ci.last_author
            params["date"] = ci.last_commit_at
            params["sha"] = ci.last_commit_sha
        plan.append((
            f"MERGE (f:File {{graph_id: $gid, path: $path}}) SET {set_clause}",
            params,
        ))
        plan.append((
            "MATCH (r:Repository {graph_id: $gid}), (f:File {graph_id: $gid, path: $path}) "
            "MERGE (r)-[:CONTAINS]->(f)",
            {"gid": slug, "path": ef.path},
        ))
        # functions
        for fn in ef.functions:
            plan.append((
                "MERGE (fn:Function {graph_id: $gid, qualified_name: $qn}) "
                "SET fn.name = $name, fn.kind = $kind, fn.start_line = $sl, fn.end_line = $el, fn.path = $fpath",
                {"gid": slug, "qn": fn.qualified_name, "name": fn.name,
                 "kind": fn.kind, "sl": fn.start_line, "el": fn.end_line, "fpath": ef.path},
            ))
            plan.append((
                "MATCH (f:File {graph_id: $gid, path: $path}), "
                "      (fn:Function {graph_id: $gid, qualified_name: $qn}) "
                "MERGE (f)-[:DEFINES]->(fn)",
                {"gid": slug, "path": ef.path, "qn": fn.qualified_name},
            ))
    # 3. IMPORTS (pass 2) — deferred like CALLS below, because the edge is a
    # MATCH-both-then-MERGE: emitting it inline above would silently drop every
    # edge whose target file hasn't been created yet, so whether a dependency
    # was recorded would depend on directory walk order.
    for ef in files:
        for imp in ef.imports:
            resolved = _resolve(imp.module, ef.path, ef.language, known_paths)
            if resolved:
                plan.append((
                    "MATCH (src:File {graph_id: $gid, path: $src}), "
                    "      (tgt:File {graph_id: $gid, path: $tgt}) "
                    "MERGE (src)-[:IMPORTS]->(tgt)",
                    {"gid": slug, "src": ef.path, "tgt": resolved},
                ))
            else:
                plan.append((
                    "MERGE (s:Symbol {graph_id: $gid, name: $name}) SET s.kind = 'import' "
                    "WITH s "
                    "MATCH (f:File {graph_id: $gid, path: $path}) "
                    "MERGE (f)-[:IMPORTS]->(s)",
                    {"gid": slug, "name": imp.module, "path": ef.path},
                ))

    # 4. CALLS resolution (pass 3) — needs all :Function nodes to exist
    all_qnames = {fn.qualified_name for ef in files for fn in ef.functions}
    for ef in files:
        for call in ef.calls:
            target_qn = _resolve_call(call, ef.path, all_qnames)
            if target_qn:
                plan.append((
                    "MATCH (caller:Function {graph_id: $gid, qualified_name: $cq}), "
                    "      (callee:Function {graph_id: $gid, qualified_name: $tq}) "
                    "MERGE (caller)-[:CALLS]->(callee)",
                    {"gid": slug, "cq": call.caller_qname, "tq": target_qn},
                ))
            else:
                plan.append((
                    "MERGE (s:Symbol {graph_id: $gid, name: $name}) SET s.kind = 'call' "
                    "WITH s "
                    "MATCH (caller:Function {graph_id: $gid, qualified_name: $cq}) "
                    "MERGE (caller)-[:CALLS]->(s)",
                    {"gid": slug, "name": call.callee_name, "cq": call.caller_qname},
                ))

    # 4. Prune tombstones for files no longer in the working tree
    plan.append((
        "MATCH (f:File {graph_id: $gid}) "
        "WHERE NOT f.path IN $paths AND f.deleted = false "
        "SET f.deleted = true "
        "WITH count(f) AS c RETURN c",
        {"gid": slug, "paths": list(known_paths)},
    ))

    # 5. Success marker — last statement, so it only lands if everything before
    # it did. A crashed ingest leaves ingest_status='running' and the previous
    # ingested_at, making the partial graph visibly incomplete.
    plan.append((
        "MATCH (r:Repository {graph_id: $gid}) "
        "SET r.ingested_at = datetime(), r.ingest_status = 'complete'",
        {"gid": slug},
    ))

    return plan


def _resolve(module: str, current_file: str, language: str, known: set[str]) -> str | None:
    """Dispatch to the language's own resolver.

    Explicitly returns None for an unregistered language rather than falling
    back to another language's resolver — a wrong resolver silently produces
    zero edges, which looks like "this repo has no internal imports".
    """
    support = support_for(language)
    if support is None:
        return None
    return support.resolve(module, current_file, known)


def _resolve_call(call: ExtractedCall, current_file: str, all_qnames: set[str]) -> str | None:
    """Resolve a call to a defining function's qualified_name, or None.

    Ordered by confidence, and — critically — *deterministic at every step*.
    The previous implementation iterated `all_qnames` (a set) and took the first
    hit, so an overloaded method name like `save` could bind to a different
    class on each ingest of the same repo. Candidates are now sorted before any
    choice is made, so repeated ingests agree.
    """
    name = call.callee_name
    if not name:
        return None

    # Every definition whose own name matches (`path::Class.save` or `path::save`).
    candidates = sorted(
        qn for qn in all_qnames
        if qn == name or qn.endswith("." + name) or qn.endswith("::" + name)
    )
    if not candidates:
        return None

    def first(matching: list[str]) -> str | None:
        return matching[0] if matching else None

    # 1. `self.m()` — the method on the class enclosing the call site.
    if call.receiver == "self" and call.caller_class:
        hit = first([
            qn for qn in candidates
            if qn.startswith(f"{current_file}::") and f"::{call.caller_class}.{name}" in qn
        ])
        if hit:
            return hit

    # 2. Receiver resolved to a class (from `x = Foo()` or a `x: Foo` annotation).
    if call.receiver and call.receiver != "self":
        hit = first([qn for qn in candidates if qn.endswith(f"::{call.receiver}.{name}")])
        if hit:
            return hit

    # 3. Same file — a local definition beats an identically named one elsewhere.
    hit = first([qn for qn in candidates if qn.startswith(f"{current_file}::")])
    if hit:
        return hit

    # 4. Unambiguous repo-wide, else the deterministic first of several.
    return candidates[0]


async def run_plan(
    adapter: Any,
    plan: list[tuple[str, dict[str, Any]]],
    batch_size: int = 200,
    progress: Callable[[int, int], None] | None = None,
) -> IngestSummary:
    """Execute the plan against the adapter, batching statements into
    `batch_size`-sized transactions (one commit per batch instead of one per
    statement), and return counts.

    `progress(done, total)` is called after each batch commits. A full-history
    ingest of a real repo is thousands of statements and can run for minutes;
    without this it is completely silent.
    """
    pruned = 0
    size = max(batch_size, 1)
    total = len(plan)
    for i in range(0, total, size):
        chunk = plan[i : i + size]
        results = await adapter._run_write_batch(chunk)
        if progress is not None:
            progress(min(i + size, total), total)
        for (cypher, _params), rows in zip(chunk, results, strict=True):
            # The prune statement returns a count via RETURN — capture it
            if "deleted = true" in cypher and rows:
                pruned = int(rows[0].get("c", 0)) if rows else 0
    files = sum(1 for c, _ in plan if "MERGE (f:File" in c)
    functions = sum(1 for c, _ in plan if "MERGE (fn:Function" in c)
    imports = sum(1 for c, _ in plan if "[:IMPORTS]" in c)
    calls = sum(1 for c, _ in plan if "[:CALLS]" in c)
    external_symbols = sum(1 for c, _ in plan if "MERGE (s:Symbol" in c)
    return IngestSummary(files=files, functions=functions, imports=imports,
                         calls=calls, external_symbols=external_symbols, pruned=pruned)
