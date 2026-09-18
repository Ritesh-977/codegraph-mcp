"""tree-sitter Java parser → ExtractedFile.

Same shape as `jsts_parser`: one Query capturing declaration/import/call nodes,
producing the shared ExtractedFunction/Import/Call DTOs.
"""

from __future__ import annotations

from typing import Any

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser, Query, QueryCursor

from codegraph.ingestion.ts_utils import (
    captured,
    enclosing_qname,
    make_function,
    node_text,
)
from codegraph.models.ingestion import (
    ExtractedCall,
    ExtractedFile,
    ExtractedFunction,
    ExtractedImport,
)

_QUERY = """
(method_declaration name: (identifier) @meth.name) @meth.def
(constructor_declaration name: (identifier) @meth.name) @meth.def
(class_declaration name: (identifier) @cls.name) @cls.def
(interface_declaration name: (identifier) @cls.name) @cls.def
(enum_declaration name: (identifier) @cls.name) @cls.def
(record_declaration name: (identifier) @cls.name) @cls.def
(import_declaration) @imp.stmt
(method_invocation name: (identifier) @call.name)
"""

_ENCLOSING_DECLS = frozenset(
    {
        "method_declaration",
        "constructor_declaration",
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
    }
)


def parse_java(path: str, source: bytes) -> ExtractedFile:
    lang = Language(tsjava.language())
    tree = Parser(lang).parse(source)
    # tree-sitter Query constructor mutates the query string; pass a copy
    cursor = QueryCursor(Query(lang, _QUERY[:]))
    captures = cursor.captures(tree.root_node)

    functions: list[ExtractedFunction] = []
    imports: list[ExtractedImport] = []
    calls: list[ExtractedCall] = []

    for node in captured(captures, "meth.name"):
        functions.append(make_function(node, source, "method", path))
    for node in captured(captures, "cls.name"):
        functions.append(make_function(node, source, "class", path))
    for imp_node in captured(captures, "imp.stmt"):
        imp = _import_from(imp_node, source)
        if imp is not None:
            imports.append(imp)
    for call_node in captured(captures, "call.name"):
        caller = enclosing_qname(call_node, source, path, _ENCLOSING_DECLS)
        calls.append(
            ExtractedCall(caller_qname=caller, callee_name=node_text(call_node, source))
        )

    return ExtractedFile(
        path=path, language="java", functions=functions, imports=imports, calls=calls
    )


def _import_from(imp_node: Any, source: bytes) -> ExtractedImport | None:
    """Turn `import a.b.C;` / `import static a.b.C.m;` / `import a.b.*;` into a DTO.

    The module string keeps the dotted form (including a trailing ``.*`` for
    wildcards) and the resolver decides what maps to a file.
    """
    raw = node_text(imp_node, source).strip()
    body = raw.removeprefix("import").strip().rstrip(";").strip()
    is_static = body.startswith("static")
    if is_static:
        body = body.removeprefix("static").strip()
    if not body:
        return None
    # Symbol: the trailing segment for a plain import, empty for a wildcard.
    last = body.rsplit(".", 1)[-1]
    symbol = "" if last == "*" else last
    return ExtractedImport(module=body, symbol=symbol, resolved_path=None)
