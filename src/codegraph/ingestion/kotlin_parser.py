"""tree-sitter Kotlin parser → ExtractedFile.

Grammar notes (verified against tree-sitter-kotlin 1.1.0, which differs from
the JS/Java grammars): the import node is `import` (not `import_header`), all
declaration names are plain `identifier` under a `name:` field, and a call's
callee lives inside a `navigation_expression` for `recv.method()` form.
"""

from __future__ import annotations

from typing import Any

import tree_sitter_kotlin as tskt
from tree_sitter import Language, Parser, Query, QueryCursor

from codegraph.ingestion.ts_utils import captured, enclosing_qname, make_function, node_text
from codegraph.models.ingestion import (
    ExtractedCall,
    ExtractedFile,
    ExtractedFunction,
    ExtractedImport,
)

_QUERY = """
(function_declaration name: (identifier) @fn.name) @fn.def
(class_declaration name: (identifier) @cls.name) @cls.def
(object_declaration name: (identifier) @cls.name) @cls.def
(import) @imp.stmt
(call_expression) @call.expr
"""

_ENCLOSING_DECLS = frozenset(
    {"function_declaration", "class_declaration", "object_declaration"}
)


def parse_kotlin(path: str, source: bytes) -> ExtractedFile:
    lang = Language(tskt.language())
    tree = Parser(lang).parse(source)
    # tree-sitter Query constructor mutates the query string; pass a copy
    cursor = QueryCursor(Query(lang, _QUERY[:]))
    captures = cursor.captures(tree.root_node)

    functions: list[ExtractedFunction] = []
    imports: list[ExtractedImport] = []
    calls: list[ExtractedCall] = []

    for node in captured(captures, "fn.name"):
        functions.append(make_function(node, source, "function", path))
    for node in captured(captures, "cls.name"):
        functions.append(make_function(node, source, "class", path))
    for imp_node in captured(captures, "imp.stmt"):
        imp = _import_from(imp_node, source)
        if imp is not None:
            imports.append(imp)
    for call_node in captured(captures, "call.expr"):
        callee = _callee_name(call_node, source)
        if callee is None:
            continue
        caller = enclosing_qname(call_node, source, path, _ENCLOSING_DECLS)
        calls.append(ExtractedCall(caller_qname=caller, callee_name=callee))

    return ExtractedFile(
        path=path, language="kotlin", functions=functions, imports=imports, calls=calls
    )


def _callee_name(call_node: Any, source: bytes) -> str | None:
    """`svc.find(id)` → "find"; `plain(1)` → "plain"."""
    first = next((c for c in call_node.children if c.is_named), None)
    if first is None:
        return None
    if first.type == "navigation_expression":
        ids = [c for c in first.children if c.type == "identifier"]
        return node_text(ids[-1], source) if ids else None
    if first.type == "identifier":
        return node_text(first, source)
    return None


def _import_from(imp_node: Any, source: bytes) -> ExtractedImport | None:
    """`import a.b.C` / `import a.b.C as D` / `import a.b.*` → DTO.

    The `as` alias is dropped: the module path is what resolves to a file.
    """
    qualified = next(
        (c for c in imp_node.children if c.type == "qualified_identifier"), None
    )
    if qualified is None:
        return None
    parts = [node_text(c, source) for c in qualified.children if c.type == "identifier"]
    if not parts:
        return None
    module = ".".join(parts)
    if any(node_text(c, source) == "*" for c in imp_node.children):
        return ExtractedImport(module=f"{module}.*", symbol="", resolved_path=None)
    return ExtractedImport(module=module, symbol=parts[-1], resolved_path=None)
