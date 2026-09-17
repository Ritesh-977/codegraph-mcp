"""Language registry: the single place a new language is wired up.

Each entry pairs a source parser (bytes → ExtractedFile) with the import
resolver for that language's module system. Adding language N+1 means adding
one row here plus its two functions — no `if/elif` chains in the CLI or the
graph builder to keep in sync.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from codegraph.models.ingestion import ExtractedFile

Parser = Callable[[str, bytes], ExtractedFile]
Resolver = Callable[[str, str, set[str]], str | None]


@dataclass(frozen=True)
class LanguageSupport:
    parse: Parser
    resolve: Resolver


def _registry() -> dict[str, LanguageSupport]:
    # Imported lazily: each parser pulls in its own tree-sitter grammar wheel,
    # and the MCP server process never parses anything.
    from codegraph.ingestion.java_parser import parse_java
    from codegraph.ingestion.jsts_parser import parse_jsts
    from codegraph.ingestion.kotlin_parser import parse_kotlin
    from codegraph.ingestion.python_parser import parse_python
    from codegraph.ingestion.resolver import (
        resolve_java_import,
        resolve_js_import,
        resolve_kotlin_import,
        resolve_python_import,
    )

    def _jsts_parser(lang: str) -> Parser:
        """parse_jsts takes the dialect as a third arg; bind it per entry."""

        def _parse(path: str, source: bytes) -> ExtractedFile:
            return parse_jsts(path, source, lang)

        return _parse

    jsts: dict[str, LanguageSupport] = {
        lang: LanguageSupport(parse=_jsts_parser(lang), resolve=resolve_js_import)
        for lang in ("js", "ts", "tsx")
    }
    return {
        "py": LanguageSupport(parse=parse_python, resolve=resolve_python_import),
        **jsts,
        "java": LanguageSupport(parse=parse_java, resolve=resolve_java_import),
        "kotlin": LanguageSupport(parse=parse_kotlin, resolve=resolve_kotlin_import),
    }


_CACHE: dict[str, LanguageSupport] | None = None


def support_for(language: str) -> LanguageSupport | None:
    """Return the parser/resolver pair for a language, or None if unsupported."""
    global _CACHE
    if _CACHE is None:
        _CACHE = _registry()
    return _CACHE.get(language)


def supported_languages() -> frozenset[str]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _registry()
    return frozenset(_CACHE)
