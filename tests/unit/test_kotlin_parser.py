"""Kotlin tree-sitter parser — extraction only, no I/O."""

from __future__ import annotations

from codegraph.ingestion.kotlin_parser import parse_kotlin

_SRC = b"""package com.foo.app

import com.foo.service.UserService
import com.foo.util.Helper as H
import com.foo.other.*

class App(val svc: UserService) {
    fun run(id: String): String {
        return svc.find(id)
    }
}

object Registry {
    fun get(): Int = plain(1)
}

fun topLevel(): Int = 42
"""


def _parsed():
    return parse_kotlin("src/main/kotlin/com/foo/app/App.kt", _SRC)


def test_language_is_kotlin() -> None:
    assert _parsed().language == "kotlin"


def test_extracts_functions_including_top_level() -> None:
    names = {f.name for f in _parsed().functions if f.kind == "function"}
    assert {"run", "get", "topLevel"} <= names


def test_extracts_class_and_object() -> None:
    names = {f.name for f in _parsed().functions if f.kind == "class"}
    assert {"App", "Registry"} <= names


def test_qualified_names_are_file_scoped() -> None:
    run = next(f for f in _parsed().functions if f.name == "run")
    assert run.qualified_name == "src/main/kotlin/com/foo/app/App.kt::run"


def test_import_alias_is_stripped_and_wildcard_kept() -> None:
    modules = {i.module for i in _parsed().imports}
    assert "com.foo.service.UserService" in modules
    assert "com.foo.util.Helper" in modules   # `as H` dropped — the path resolves, not the alias
    assert "com.foo.other.*" in modules


def test_calls_resolve_through_navigation_and_plain() -> None:
    calls = {(c.callee_name, c.caller_qname) for c in _parsed().calls}
    path = "src/main/kotlin/com/foo/app/App.kt"
    assert ("find", f"{path}::run") in calls    # svc.find(id) -> "find"
    assert ("plain", f"{path}::get") in calls   # bare call
