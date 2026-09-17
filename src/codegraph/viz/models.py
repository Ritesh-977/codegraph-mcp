"""UI wire-format models for codegraph-viz.

Independent of the MCP/DTO models in ``codegraph.models``: this is the
contract between the FastAPI layer and the React frontend, and it is free to
change shape without touching a single MCP tool schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from codegraph.models.common import MAX_TRAVERSAL_HOPS


class GraphNode(BaseModel):
    id: str
    kind: Literal["file", "dir_cluster", "symbol", "function"]
    label: str
    path: str | None = None
    language: str | None = None
    file_count: int | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    type: Literal["IMPORTS", "CALLS", "DEFINES"]
    weight: int = 1


class GraphStats(BaseModel):
    file_count: int
    edge_count: int
    truncated: bool = False
    view: str


class GraphPayload(BaseModel):
    graph_id: str
    view: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stats: GraphStats


class SubgraphRequest(BaseModel):
    graph_id: str
    seed_path: str
    direction: Literal["imports", "imported_by", "both"] = "both"
    depth: int = Field(default=2, ge=1, le=MAX_TRAVERSAL_HOPS)
    include_symbols: bool = True


class ImpactRequest(BaseModel):
    graph_id: str
    seed_path: str
    max_hops: int = Field(default=2, ge=1, le=MAX_TRAVERSAL_HOPS)


class ImpactRing(BaseModel):
    hop: int
    paths: list[str]


class ImpactPayload(BaseModel):
    graph_id: str
    seed_path: str
    rings: list[ImpactRing]
    callers: list[str] = []
    calls: list[str] = []
    truncated: bool = False


class ExpandResult(BaseModel):
    """One level below a directory: its files plus its child directory clusters."""

    graph_id: str
    dir_prefix: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class FunctionInfo(BaseModel):
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int


class FileDetailResponse(BaseModel):
    graph_id: str
    path: str
    language: str | None = None
    last_author: str | None = None
    last_commit_at: str | None = None
    last_commit_sha: str | None = None
    content: str
    start_line: int
    end_line: int
    truncated: bool = False
    functions: list[FunctionInfo] = []
    imported_by: list[str] = []
    imports: list[str] = []
    external_symbols: list[str] = []
