# tests/unit/test_resolver.py
"""Pure-logic import-path resolution — no I/O."""

from __future__ import annotations

from codegraph.ingestion.resolver import (
    resolve_java_import,
    resolve_js_import,
    resolve_kotlin_import,
    resolve_python_import,
)


def test_py_absolute_import_resolves_to_module_file() -> None:
    known = {"src/codegraph/ingestion/resolver.py", "src/codegraph/__init__.py"}
    assert resolve_python_import("codegraph.ingestion.resolver", "src/main.py", known) == "src/codegraph/ingestion/resolver.py"


def test_py_package_import_resolves_to_init() -> None:
    known = {"src/codegraph/__init__.py"}
    assert resolve_python_import("codegraph", "src/main.py", known) == "src/codegraph/__init__.py"


def test_py_stdlib_not_resolved() -> None:
    assert resolve_python_import("os.path", "src/main.py", {"src/main.py"}) is None


def test_py_relative_import_resolves() -> None:
    known = {"pkg/sub/mod.py", "pkg/__init__.py"}
    assert resolve_python_import(".sub.mod", "pkg/__init__.py", known) == "pkg/sub/mod.py"


def test_js_relative_import_resolves_with_extension() -> None:
    known = {"src/auth.js", "src/index.js"}
    assert resolve_js_import("./auth", "src/index.js", known) == "src/auth.js"


def test_js_relative_import_resolves_index() -> None:
    known = {"src/utils/index.ts"}
    assert resolve_js_import("./utils", "src/main.ts", known) == "src/utils/index.ts"


def test_js_external_not_resolved() -> None:
    assert resolve_js_import("react", "src/main.ts", {"src/main.ts"}) is None


def test_js_esm_spec_with_explicit_extension_resolves() -> None:
    """Node ESM requires the extension in relative specs, so './x.js' must
    match the file directly rather than being probed as './x.js.js'."""
    known = {"server/middleware/multer.js", "server/routes/itemRoutes.js"}
    assert (
        resolve_js_import("../middleware/multer.js", "server/routes/itemRoutes.js", known)
        == "server/middleware/multer.js"
    )


def test_js_same_dir_spec_with_extension_resolves() -> None:
    known = {"src/auth.js", "src/index.js"}
    assert resolve_js_import("./auth.js", "src/index.js", known) == "src/auth.js"


def test_ts_source_resolved_from_js_spec() -> None:
    """TypeScript ESM writes './x.js' for a file that is actually './x.ts'."""
    known = {"src/auth.ts", "src/index.ts"}
    assert resolve_js_import("./auth.js", "src/index.ts", known) == "src/auth.ts"


# --- Java ---------------------------------------------------------------

_JAVA_KNOWN = {
    "src/main/java/com/foo/app/App.java",
    "src/main/java/com/foo/service/UserService.java",
    "src/main/java/com/foo/util/Helper.java",
}
_JAVA_CALLER = "src/main/java/com/foo/app/App.java"


def test_java_import_resolves_through_maven_source_root() -> None:
    """Suffix matching handles src/main/java/ without hardcoding it."""
    assert (
        resolve_java_import("com.foo.service.UserService", _JAVA_CALLER, _JAVA_KNOWN)
        == "src/main/java/com/foo/service/UserService.java"
    )


def test_java_static_import_strips_member() -> None:
    assert (
        resolve_java_import("com.foo.util.Helper.help", _JAVA_CALLER, _JAVA_KNOWN)
        == "src/main/java/com/foo/util/Helper.java"
    )


def test_java_wildcard_import_unresolved() -> None:
    """`import com.foo.other.*` targets a package dir, not a file."""
    assert resolve_java_import("com.foo.service.*", _JAVA_CALLER, _JAVA_KNOWN) is None


def test_java_external_dependency_unresolved() -> None:
    assert resolve_java_import("java.util.List", _JAVA_CALLER, _JAVA_KNOWN) is None


def test_java_resolves_without_source_root() -> None:
    known = {"com/foo/Bar.java", "com/foo/App.java"}
    assert resolve_java_import("com.foo.Bar", "com/foo/App.java", known) == "com/foo/Bar.java"


def test_java_can_resolve_kotlin_file_in_mixed_project() -> None:
    """Mixed JVM projects import across languages both ways — a .java file
    importing a Kotlin class must resolve (caught on square/okio, where Java
    benchmarks import Kotlin's okio.Buffer)."""
    known = {
        "okio/src/jvmMain/kotlin/okio/Buffer.kt",
        "okio/jvm/jmh/src/jmh/java/com/squareup/okio/benchmarks/Bench.java",
    }
    caller = "okio/jvm/jmh/src/jmh/java/com/squareup/okio/benchmarks/Bench.java"
    assert resolve_java_import("okio.Buffer", caller, known) == "okio/src/jvmMain/kotlin/okio/Buffer.kt"


# --- Kotlin -------------------------------------------------------------

_KT_KNOWN = {
    "src/main/kotlin/com/foo/app/App.kt",
    "src/main/kotlin/com/foo/service/UserService.kt",
    "src/main/java/com/foo/legacy/Legacy.java",
}
_KT_CALLER = "src/main/kotlin/com/foo/app/App.kt"


def test_kotlin_import_resolves() -> None:
    assert (
        resolve_kotlin_import("com.foo.service.UserService", _KT_CALLER, _KT_KNOWN)
        == "src/main/kotlin/com/foo/service/UserService.kt"
    )


def test_kotlin_can_resolve_java_file_in_mixed_project() -> None:
    assert (
        resolve_kotlin_import("com.foo.legacy.Legacy", _KT_CALLER, _KT_KNOWN)
        == "src/main/java/com/foo/legacy/Legacy.java"
    )


def test_kotlin_wildcard_unresolved() -> None:
    assert resolve_kotlin_import("com.foo.service.*", _KT_CALLER, _KT_KNOWN) is None
