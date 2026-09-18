"""tree-sitter JS/TS/TSX parser → ExtractedFile.

Loads per-language grammar wheels and runs a single Query capturing
function/class/import/call nodes.
"""

from __future__ import annotations

from typing import Any

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser, Query, QueryCursor

from codegraph.ingestion.ts_utils import (
    captured,
    enclosing_qname,
    make_function,
    node_text,
    walk,
)
from codegraph.models.ingestion import (
    ExtractedCall,
    ExtractedFile,
    ExtractedFunction,
    ExtractedImport,
)

_ENCLOSING_DECLS = frozenset(
    {
        "function_declaration",
        "method_definition",
        "class_declaration",
        # Arrow/function expressions carry no name of their own — enclosing_qname
        # reads it from the parent declarator/pair. Without them in this set the
        # ancestor walk skips *past* every enclosing arrow, so a call inside a
        # React component was attributed to some outer function, or <module>.
        "arrow_function",
        "function_expression",
    }
)

# Modern JS/TS is dominated by `const X = () => {}` rather than `function X(){}`;
# these two captures are the difference between seeing a React codebase and
# seeing almost none of it.
_ARROW_CAPTURES = """
(variable_declarator name: (identifier) @fn.name value: (arrow_function)) @fn.def
(variable_declarator name: (identifier) @fn.name value: (function_expression)) @fn.def
(pair key: (property_identifier) @fn.name value: (arrow_function)) @fn.def
(pair key: (property_identifier) @fn.name value: (function_expression)) @fn.def
(export_statement value: (arrow_function) @fn.anon)
(export_statement value: (function_expression) @fn.anon)
"""

_LANGS = {
    "js": lambda: Language(tsjs.language()),
    "ts": lambda: Language(tsts.language_typescript()),
    "tsx": lambda: Language(tsts.language_tsx()),
}

# JavaScript grammar uses 'identifier' for class names, TS/TSX use 'type_identifier'
_QUERY_JS = """
(function_declaration name: (identifier) @fn.name) @fn.def
(method_definition name: (property_identifier) @meth.name) @meth.def
(class_declaration name: (identifier) @cls.name) @cls.def
(import_statement) @imp.stmt
(call_expression function: (identifier) @call.name)
(call_expression function: (member_expression property: (property_identifier) @call.name))
""" + _ARROW_CAPTURES

_QUERY_TS = """
(function_declaration name: (identifier) @fn.name) @fn.def
(method_definition name: (property_identifier) @meth.name) @meth.def
(class_declaration name: (type_identifier) @cls.name) @cls.def
(import_statement) @imp.stmt
(call_expression function: (identifier) @call.name)
(call_expression function: (member_expression property: (property_identifier) @call.name))
""" + _ARROW_CAPTURES


def parse_jsts(path: str, source: bytes, language: str) -> ExtractedFile:
    if language not in _LANGS:
        raise ValueError(f"unsupported language {language!r}")
    lang = _LANGS[language]()
    parser = Parser(lang)
    tree = parser.parse(source)
    # tree-sitter Query constructor mutates the query string; pass a copy
    query_str = _QUERY_JS[:] if language == "js" else _QUERY_TS[:]
    q = Query(lang, query_str)
    cursor = QueryCursor(q)
    captures = cursor.captures(tree.root_node)

    functions: list[ExtractedFunction] = []
    imports: list[ExtractedImport] = []
    calls: list[ExtractedCall] = []

    for node in captured(captures, "fn.name"):
        functions.append(make_function(node, source, "function", path))
    for node in captured(captures, "meth.name"):
        functions.append(make_function(node, source, "method", path))
    for node in captured(captures, "cls.name"):
        functions.append(make_function(node, source, "class", path))
    for node in captured(captures, "fn.anon"):
        # `export default () => {}` has no name anywhere in the tree. Give it a
        # synthetic one so the component is addressable at all; `path::name`
        # already keeps it unique per file.
        functions.append(
            ExtractedFunction(
                name="default",
                qualified_name=f"{path}::default",
                kind="function",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            )
        )
    for imp_node in captured(captures, "imp.stmt"):
        imports.extend(_imports_from(imp_node, source))
    for call_node in captured(captures, "call.name"):
        caller = enclosing_qname(call_node, source, path, _ENCLOSING_DECLS)
        calls.append(
            ExtractedCall(caller_qname=caller, callee_name=node_text(call_node, source))
        )

    return ExtractedFile(
        path=path, language=language, functions=functions, imports=imports, calls=calls
    )


def _imports_from(imp_node: Any, source: bytes) -> list[ExtractedImport]:
    """Best-effort: pull the string-literal source and the imported names."""
    out: list[ExtractedImport] = []
    mod = ""
    symbols: list[str] = []
    for child in imp_node.children:
        t = child.type
        if t == "import_clause":
            for sub in walk(child):
                if sub.type == "identifier":
                    symbols.append(node_text(sub, source))
        if t == "string":
            mod = node_text(child, source).strip('"').strip("'")
    for sym in symbols:
        out.append(ExtractedImport(module=mod, symbol=sym, resolved_path=None))
    if not out and mod:
        out.append(ExtractedImport(module=mod, symbol="", resolved_path=None))
    return out
