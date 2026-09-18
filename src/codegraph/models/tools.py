"""Pydantic args/result models for each MCP tool. Schemas auto-derive to the LLM."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from codegraph.models.common import MAX_TRAVERSAL_HOPS, FilePath, GraphId


class RepoInfo(BaseModel):
    graph_id: str
    name: str
    url: str
    default_branch: str | None = None
    ingested_at: str | None = None
    # "running" means an ingest started but never finished — the graph is
    # partial and should not be trusted as a complete picture.
    ingest_status: str | None = None


class ListReposResult(BaseModel):
    repos: list[RepoInfo]


class InitRepositoryNodeArgs(BaseModel):
    graph_id: GraphId


class InitRepositoryNodeResult(BaseModel):
    graph_id: str
    name: str
    url: str
    file_count: int
    function_count: int
    ingest_status: str | None = None


class GetRepoStructureArgs(BaseModel):
    graph_id: GraphId
    path: str = ""
    limit: int = Field(default=200, ge=1, le=1000)


class StructureEntry(BaseModel):
    name: str
    type: str  # "file" | "dir"
    language: str | None = None


class GetRepoStructureResult(BaseModel):
    path: str
    entries: list[StructureEntry]
    truncated: bool = False


class FindFileDependenciesArgs(BaseModel):
    graph_id: GraphId
    file_path: FilePath
    direction: Literal["imports", "imported_by", "both"] = "both"
    max_hops: int = Field(default=2, ge=0, le=MAX_TRAVERSAL_HOPS)


class DependencyEntry(BaseModel):
    path: str
    kind: str  # "file" | "function"
    via: str   # "imports" | "imported_by" | "calls" | "called_by"
    hop: int


class ExternalSymbolEntry(BaseModel):
    name: str
    kind: str  # "import" | "call"


class FindFileDependenciesResult(BaseModel):
    file: dict[str, object]
    imported_by: list[DependencyEntry] = Field(default_factory=list)
    imports: list[DependencyEntry] = Field(default_factory=list)
    callers: list[DependencyEntry] = Field(default_factory=list)
    calls: list[DependencyEntry] = Field(default_factory=list)
    external_symbols: list[ExternalSymbolEntry] = Field(default_factory=list)
    truncated: bool = False
    hint: str | None = None


class SearchNodesArgs(BaseModel):
    graph_id: GraphId
    query: str = Field(min_length=1)
    kind: Literal["any", "function", "file"] = "any"
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchHit(BaseModel):
    id: str | None = None
    name: str
    qualified_name: str | None = None
    path: str | None = None
    kind: str
    score: float = 1.0


class SearchNodesResult(BaseModel):
    hits: list[SearchHit]
    # Set when a full page came back, i.e. more results may exist. Mirrors the
    # `truncated` convention used by the other list-returning tools.
    next_offset: int | None = None


class GetNodeDetailArgs(BaseModel):
    graph_id: GraphId
    node_id: str


class GetNodeDetailResult(BaseModel):
    id: str
    name: str
    kind: str
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None


class GetFileContentArgs(BaseModel):
    graph_id: GraphId
    file_path: FilePath
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class GetFileContentResult(BaseModel):
    path: str
    language: str | None = None
    content: str
    start_line: int
    end_line: int
    truncated: bool = False


class GetFileMetadataArgs(BaseModel):
    graph_id: GraphId
    file_path: FilePath


class GetFileMetadataResult(BaseModel):
    path: str
    language: str | None = None
    # Null for repos ingested without git history (e.g. a shallow clone from
    # before INGEST_DEPTH defaulted to full).
    last_author: str | None = None
    last_commit_at: str | None = None
    last_commit_sha: str | None = None


class GetFunctionSourceArgs(BaseModel):
    graph_id: GraphId
    node_id: str


class GetFunctionSourceResult(BaseModel):
    node_id: str
    name: str
    path: str
    start_line: int
    end_line: int
    content: str
    truncated: bool = False
