"""Pure-logic import-path → repo-rel file path resolution. No I/O.

Conservative: returns None for anything that cannot be resolved to a file
that exists in `known_files`. Callers turn unresolved imports into :Symbol leaves.
"""

from __future__ import annotations

import os


def _posix(path: str) -> str:
    return path.replace("\\", "/")


def _try_candidates(candidates: list[str], known: set[str]) -> str | None:
    for c in candidates:
        if c in known:
            return c
    return None


def resolve_python_import(module: str, current_file: str, known_files: set[str]) -> str | None:
    """Resolve `from a.b import c` / `import a.b` → repo-rel path or None.

    Handles: absolute `a.b.c`, relative `.b`, `..b`.
    """
    if not module:
        return None
    # Relative import
    if module.startswith("."):
        dots = len(module) - len(module.lstrip("."))
        rel = module.lstrip(".")
        base_dir = os.path.dirname(current_file)
        for _ in range(dots - 1):
            base_dir = os.path.dirname(base_dir)
        if rel:
            rel_path = _posix(os.path.normpath(os.path.join(base_dir, rel.replace(".", "/"))))
        else:
            rel_path = _posix(base_dir)
        return _try_candidates(
            [f"{rel_path}.py", f"{rel_path}/__init__.py"], known_files
        )
    # Absolute — try direct path, then suffix match against known files
    # (handles src-layout where `pkg.x` maps to `src/pkg/x.py`).
    parts = module.split(".")
    base = "/".join(parts)
    direct = _try_candidates([f"{base}.py", f"{base}/__init__.py"], known_files)
    if direct is not None:
        return direct
    for suffix in (f"/{base}.py", f"/{base}/__init__.py"):
        for f in known_files:
            if f.endswith(suffix):
                return f
    return None


# JVM projects mix languages freely — Java code imports Kotlin classes and vice
# versa — so both resolvers try both extensions, own language first.
_JAVA_SUFFIXES = (".java", ".kt")
_KOTLIN_SUFFIXES = (".kt", ".java")


def _resolve_jvm_import(module: str, known_files: set[str], suffixes: tuple[str, ...]) -> str | None:
    """Shared JVM resolution: dotted package path → repo-rel file.

    `com.foo.Bar` → any known file ending `/com/foo/Bar.<ext>`. Suffix matching
    (the same trick `resolve_python_import` uses for src-layout) means Maven and
    Gradle source roots — `src/main/java/`, `src/main/kotlin/` — resolve without
    being hardcoded. Wildcards (`com.foo.*`) target a package directory rather
    than a file, so they stay unresolved and become :Symbol leaves.
    """
    if not module or module.endswith(".*"):
        return None
    base = module.replace(".", "/")
    for ext in suffixes:
        direct = f"{base}{ext}"
        if direct in known_files:
            return direct
        needle = f"/{base}{ext}"
        for f in known_files:
            if f.endswith(needle):
                return f
    return None


def resolve_java_import(module: str, current_file: str, known_files: set[str]) -> str | None:
    """Resolve a Java import → repo-rel path or None.

    Handles `import com.foo.Bar;` and `import static com.foo.Bar.baz;` (the
    caller passes the dotted body; for a static import the trailing member is
    stripped here by also trying the parent path).

    Known gap: classes in the *same package* need no import statement, so those
    dependencies produce no edge. Synthesizing same-directory edges would
    invent large fan-out that isn't in the source, so we stay conservative.
    """
    hit = _resolve_jvm_import(module, known_files, _JAVA_SUFFIXES)
    if hit is not None:
        return hit
    # `import static com.foo.Bar.baz;` — drop the trailing member and retry.
    if "." in module and not module.endswith(".*"):
        parent = module.rsplit(".", 1)[0]
        return _resolve_jvm_import(parent, known_files, _JAVA_SUFFIXES)
    return None


def resolve_kotlin_import(module: str, current_file: str, known_files: set[str]) -> str | None:
    """Resolve a Kotlin import → repo-rel path or None.

    Fuzzier than Java by design of the language: Kotlin allows several
    top-level declarations per file and does not require the filename to match
    the declaration, so `com.foo.Bar` may live in `com/foo/Utils.kt`. We try the
    conventional `com/foo/Bar.kt` (and `.java`, for mixed JVM projects) and
    otherwise leave it unresolved rather than guess.
    """
    hit = _resolve_jvm_import(module, known_files, _KOTLIN_SUFFIXES)
    if hit is not None:
        return hit
    # A member import (`import com.foo.Bar.baz`) — retry against the parent.
    if "." in module and not module.endswith(".*"):
        parent = module.rsplit(".", 1)[0]
        return _resolve_jvm_import(parent, known_files, _KOTLIN_SUFFIXES)
    return None


def resolve_js_import(spec: str, current_file: str, known_files: set[str]) -> str | None:
    """Resolve a JS/TS import spec → repo-rel path or None. Only relative specs resolve."""
    if not spec.startswith("."):
        return None
    base_dir = os.path.dirname(current_file)
    rel = _posix(os.path.normpath(os.path.join(base_dir, spec)))
    # Exact match first: Node ESM *requires* the extension in relative specs
    # ("./x.js"), so the spec often already names the file directly.
    candidates = [rel]
    # TypeScript ESM writes "./x.js" for a source file that is actually "./x.ts".
    if rel.endswith(".js"):
        candidates += [f"{rel[:-3]}.ts", f"{rel[:-3]}.tsx"]
    elif rel.endswith(".jsx"):
        candidates.append(f"{rel[:-4]}.tsx")
    # Then extension-less specs ("./x") and directory/index resolution.
    candidates += [
        f"{rel}.js", f"{rel}.ts", f"{rel}.tsx", f"{rel}.jsx",
        f"{rel}/index.js", f"{rel}/index.ts", f"{rel}/index.tsx", f"{rel}/index.jsx",
    ]
    return _try_candidates(candidates, known_files)
