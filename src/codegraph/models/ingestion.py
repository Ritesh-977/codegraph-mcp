"""DTOs for parser output — shared by parsers + graph_builder."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExtractedFunction:
    name: str
    qualified_name: str
    kind: str  # "function" | "method" | "class"
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ExtractedImport:
    module: str            # raw module string, e.g. "a.b" or "./auth"
    symbol: str            # imported name or "" for bare import
    resolved_path: str | None  # repo-rel path if resolver matched, else None


@dataclass(frozen=True)
class ExtractedCall:
    caller_qname: str      # qualified name of the enclosing function (or "<module>")
    callee_name: str       # raw callee name as written
    # Receiver of an attribute call — "self" for `self.m()`, the variable name
    # for `user.save()`, None for a bare `helper()`. Used only to disambiguate
    # during resolution; never stored in the graph.
    receiver: str | None = None
    # Class enclosing the call site, so `self.m()` can bind to the right class.
    caller_class: str | None = None


@dataclass
class ExtractedFile:
    path: str
    language: str
    functions: list[ExtractedFunction] = field(default_factory=list)
    imports: list[ExtractedImport] = field(default_factory=list)
    calls: list[ExtractedCall] = field(default_factory=list)
