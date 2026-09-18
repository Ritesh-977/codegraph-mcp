"""Shared tree-sitter helpers used by every grammar-based parser.

Extracted from `jsts_parser` once a third tree-sitter language (Java/Kotlin)
arrived rather than copying the same normalization logic per parser.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from codegraph.models.ingestion import ExtractedFunction


def captured(captures: Any, name: str) -> list[Any]:
    """Normalize the captures return across tree-sitter binding versions.

    ``QueryCursor.captures`` returns either a ``dict[str, list[Node]]`` (newer
    bindings) or a ``list[tuple[str, Node]]`` (older bindings / ``matches``).
    """
    if isinstance(captures, dict):
        return list(captures.get(name, []))
    return [n for k, n in captures if k == name]


def node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def walk(node: Any) -> Iterator[Any]:
    yield node
    for c in node.children:
        yield from walk(c)


def make_function(
    name_node: Any, source: bytes, kind: str, file_path: str
) -> ExtractedFunction:
    """Build an ExtractedFunction from a captured *name* node.

    The qualified name is scoped per-file (``path::name``) so that two files
    each defining `authenticate` don't MERGE into one Function node. Line range
    comes from the enclosing declaration node, not the bare name token.
    """
    name = node_text(name_node, source)
    parent = name_node.parent
    start = (parent.start_point[0] + 1) if parent else (name_node.start_point[0] + 1)
    end = (parent.end_point[0] + 1) if parent else (name_node.end_point[0] + 1)
    return ExtractedFunction(
        name=name,
        qualified_name=f"{file_path}::{name}",
        kind=kind,
        start_line=start,
        end_line=end,
    )


def enclosing_qname(
    node: Any, source: bytes, file_path: str, decl_types: frozenset[str]
) -> str:
    """Qualified name of the *innermost* declaration enclosing `node`, or ``"<module>"``.

    Uses the grammar's ``name:`` field rather than scanning children, so a
    declaration whose other children are also identifiers (e.g. a Java return
    type) can't be mistaken for the name.

    Arrow and function expressions have no name of their own — the name lives on
    whatever binds them (``const x = () => {}`` / ``{ key: () => {} }``), so it
    is read from the parent. A genuinely anonymous one (a callback argument,
    say) is skipped and the walk continues outward, which is what makes
    attribution land on the nearest *named* owner.
    """
    current = node.parent
    while current is not None:
        if current.type in decl_types:
            name_node = current.child_by_field_name("name")
            if name_node is not None:
                return f"{file_path}::{node_text(name_node, source)}"
            bound = _binding_name(current, source)
            if bound is not None:
                return f"{file_path}::{bound}"
        current = current.parent
    return "<module>"


def _binding_name(fn_node: Any, source: bytes) -> str | None:
    """Name for an unnamed function/arrow, taken from whatever binds it.

    Matches how the parser names these declarations, so a call inside one is
    attributed to the same node the declaration produced.
    """
    parent = fn_node.parent
    if parent is None:
        return None
    if parent.type == "variable_declarator":
        name_node = parent.child_by_field_name("name")
        return node_text(name_node, source) if name_node is not None else None
    if parent.type == "pair":
        key_node = parent.child_by_field_name("key")
        return node_text(key_node, source) if key_node is not None else None
    if parent.type == "export_statement":
        # `export default () => {}` — synthetic name, matching the parser.
        return "default"
    return None
