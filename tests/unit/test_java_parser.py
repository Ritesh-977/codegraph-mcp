"""Java tree-sitter parser — extraction only, no I/O."""

from __future__ import annotations

from codegraph.ingestion.java_parser import parse_java

_SRC = b"""package com.foo.app;

import com.foo.service.UserService;
import static com.foo.util.Helper.help;
import com.foo.other.*;

public class App {
    private UserService svc;

    public App() {
        help();
    }

    public String run(String id) {
        return svc.find(id);
    }
}

interface Greeter { String hi(); }

enum Color { RED }
"""


def _parsed():
    return parse_java("src/main/java/com/foo/app/App.java", _SRC)


def test_language_is_java() -> None:
    assert _parsed().language == "java"


def test_extracts_methods_and_constructor() -> None:
    names = {f.name for f in _parsed().functions if f.kind == "method"}
    assert {"App", "run", "hi"} <= names


def test_extracts_class_interface_enum() -> None:
    names = {f.name for f in _parsed().functions if f.kind == "class"}
    assert {"App", "Greeter", "Color"} <= names


def test_qualified_names_are_file_scoped() -> None:
    run = next(f for f in _parsed().functions if f.name == "run")
    assert run.qualified_name == "src/main/java/com/foo/app/App.java::run"
    assert run.start_line < run.end_line


def test_extracts_all_import_forms() -> None:
    modules = {i.module for i in _parsed().imports}
    assert "com.foo.service.UserService" in modules
    assert "com.foo.util.Helper.help" in modules  # static import keeps the member
    assert "com.foo.other.*" in modules           # wildcard keeps the star


def test_call_is_attributed_to_enclosing_method() -> None:
    calls = {(c.callee_name, c.caller_qname) for c in _parsed().calls}
    path = "src/main/java/com/foo/app/App.java"
    assert ("find", f"{path}::run") in calls
    assert ("help", f"{path}::App") in calls  # inside the constructor
