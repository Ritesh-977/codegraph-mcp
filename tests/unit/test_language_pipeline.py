"""End-to-end walk → parse → resolve, per language, without Neo4j.

Guards the failure mode that unit-testing parsers and resolvers separately
misses: a language whose imports all silently become :Symbol leaves because
the wrong resolver ran (or none did). That bug shipped twice — JS ESM specs
carrying a `.js` extension, and `_resolve`'s old `else: resolve_js_import`
fallback — and looks exactly like "this repo has no internal dependencies".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.ingestion.languages import support_for
from codegraph.ingestion.walker import walk_repo

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _resolved_imports(repo_dir: Path) -> tuple[dict[str, set[str]], list[str]]:
    """Return (path -> resolved import targets, unresolved module strings)."""
    entries = walk_repo(repo_dir)
    parsed = []
    for e in entries:
        support = support_for(e.language)
        if support is not None:
            parsed.append(support.parse(e.path, e.abspath.read_bytes()))

    known = {p.path for p in parsed}
    resolved: dict[str, set[str]] = {}
    unresolved: list[str] = []
    for pf in parsed:
        support = support_for(pf.language)
        assert support is not None
        for imp in pf.imports:
            hit = support.resolve(imp.module, pf.path, known)
            if hit is None:
                unresolved.append(imp.module)
            else:
                resolved.setdefault(pf.path, set()).add(hit)
    return resolved, unresolved


@pytest.mark.parametrize(
    "repo,app,service,repo_file",
    [
        (
            "java_repo",
            "src/main/java/com/foo/app/App.java",
            "src/main/java/com/foo/service/UserService.java",
            "src/main/java/com/foo/repo/UserRepo.java",
        ),
        (
            "kotlin_repo",
            "src/main/kotlin/com/foo/app/App.kt",
            "src/main/kotlin/com/foo/service/UserService.kt",
            "src/main/kotlin/com/foo/repo/UserRepo.kt",
        ),
    ],
)
def test_internal_imports_resolve_to_files(
    repo: str, app: str, service: str, repo_file: str
) -> None:
    """The 2-hop chain App -> UserService -> UserRepo must be real File edges,
    which is what makes find_file_dependencies(max_hops=2) able to answer."""
    resolved, unresolved = _resolved_imports(_FIXTURES / repo)

    assert resolved.get(app) == {service}, f"App should import UserService; got {resolved.get(app)}"
    assert resolved.get(service) == {repo_file}
    assert unresolved == [], f"internal imports left unresolved: {unresolved}"


@pytest.mark.parametrize("repo", ["java_repo", "kotlin_repo"])
def test_functions_are_extracted(repo: str) -> None:
    entries = walk_repo(_FIXTURES / repo)
    total = 0
    for e in entries:
        support = support_for(e.language)
        if support is not None:
            total += len(support.parse(e.path, e.abspath.read_bytes()).functions)
    # 3 classes + 3 methods across the three fixture files
    assert total >= 6, f"expected >=6 declarations, got {total}"


def test_modern_js_declarations_are_not_invisible() -> None:
    """Coverage guard for the Phase 4.1 regression: a real React repo yielded
    31 declarations across 121 files because arrow consts were never captured,
    so an entire component file could extract *zero* functions."""
    names: set[str] = set()
    for e in walk_repo(_FIXTURES / "jsts_repo"):
        support = support_for(e.language)
        if support is not None:
            parsed = support.parse(e.path, e.abspath.read_bytes())
            names |= {f.name for f in parsed.functions}
    # classic declarations plus arrow consts, nested arrow, and default export
    assert {"authenticate", "main", "useSession", "Panel", "refresh", "default"} <= names
