"""Graph builder — assert Cypher strings + params (no DB)."""

from __future__ import annotations

from codegraph.ingestion.commits import CommitInfo
from codegraph.ingestion.graph_builder import build_ingest_plan
from codegraph.models.ingestion import (
    ExtractedCall,
    ExtractedFile,
    ExtractedFunction,
    ExtractedImport,
)


def _fixture_file() -> ExtractedFile:
    return ExtractedFile(
        path="src/auth.py", language="py",
        functions=[ExtractedFunction("authenticate", "authenticate", "function", 3, 5)],
        imports=[ExtractedImport("os", "", None)],
        calls=[ExtractedCall("authenticate", "hash")],
    )


def test_plan_has_repository_merge() -> None:
    plan = build_ingest_plan(
        slug="o/n", url="https://github.com/o/n", branch="main",
        files=[_fixture_file()], commits={}, known_paths={"src/auth.py"},
    )
    assert any("Repository" in cy and "MERGE" in cy for cy, _ in plan)


def test_plan_has_file_merge_with_commit_info() -> None:
    commits = {"src/auth.py": CommitInfo("sha1", "Alice", "2026-07-20T10:00:00+00:00")}
    plan = build_ingest_plan(
        slug="o/n", url="https://github.com/o/n", branch="main",
        files=[_fixture_file()], commits=commits, known_paths={"src/auth.py"},
    )
    assert any("File" in cy and "last_author" in cy for cy, _ in plan)


def test_plan_has_function_merge_and_defines_edge() -> None:
    plan = build_ingest_plan(
        slug="o/n", url="https://github.com/o/n", branch="main",
        files=[_fixture_file()], commits={}, known_paths={"src/auth.py"},
    )
    assert any("Function" in cy and "DEFINES" in cy for cy, _ in plan)


def test_plan_has_unresolved_import_as_symbol() -> None:
    plan = build_ingest_plan(
        slug="o/n", url="https://github.com/o/n", branch="main",
        files=[_fixture_file()], commits={}, known_paths={"src/auth.py"},
    )
    assert any("Symbol" in cy and "IMPORTS" in cy for cy, _ in plan)


def test_plan_has_calls_resolution_pass() -> None:
    plan = build_ingest_plan(
        slug="o/n", url="https://github.com/o/n", branch="main",
        files=[_fixture_file()], commits={}, known_paths={"src/auth.py"},
    )
    assert any("CALLS" in cy for cy, _ in plan)


def test_plan_has_prune_step() -> None:
    plan = build_ingest_plan(
        slug="o/n", url="https://github.com/o/n", branch="main",
        files=[_fixture_file()], commits={}, known_paths={"src/auth.py"},
    )
    assert any("deleted = true" in cy for cy, _ in plan)


def test_import_edges_emitted_after_all_file_nodes() -> None:
    """A File->File IMPORTS edge is a MATCH-both-then-MERGE, so every File node
    must already exist when it runs. Emitting these inline in the file loop
    silently dropped any edge whose target came later in walk order — i.e.
    whether a dependency was recorded depended on directory names.
    """
    # App is listed first (as walk order gives: app/ before svc/), so its
    # import target does not yet exist during pass 1.
    app_path = "src/main/java/com/foo/app/App.java"
    svc_path = "src/main/java/com/foo/svc/UserService.java"
    a = ExtractedFile(
        path=app_path, language="java",
        imports=[ExtractedImport("com.foo.svc.UserService", "UserService", None)],
    )
    b = ExtractedFile(path=svc_path, language="java")
    plan = build_ingest_plan(
        slug="o/n", url="https://github.com/o/n", branch="main",
        files=[a, b], commits={}, known_paths={app_path, svc_path},
    )
    last_file_merge = max(i for i, (cy, _) in enumerate(plan) if "MERGE (f:File" in cy)
    import_edges = [i for i, (cy, _) in enumerate(plan) if "[:IMPORTS]->(tgt" in cy]
    assert import_edges, "expected a resolved File->File IMPORTS edge"
    assert min(import_edges) > last_file_merge


def test_plan_all_cypher_parameterized() -> None:
    """No Cypher should contain f-string-formatted values — only $param placeholders."""
    plan = build_ingest_plan(
        slug="o/n", url="https://github.com/o/n", branch="main",
        files=[_fixture_file()], commits={}, known_paths={"src/auth.py"},
    )
    for cy, params in plan:
        # Every param referenced in Cypher as $name must exist in params dict
        import re
        refs = set(re.findall(r"\$(\w+)", cy))
        for ref in refs:
            assert ref in params, f"Cypher references ${ref} but params dict lacks it: {params}"
