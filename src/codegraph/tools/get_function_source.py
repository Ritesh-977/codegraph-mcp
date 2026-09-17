"""get_function_source tool — return a function's body by line range, reusing
the node id from search_nodes/get_node_detail. Reads from the on-disk clone
`repos_dir` already holds (see design doc §2.2)."""

from __future__ import annotations

from pathlib import Path

from codegraph.models.tools import GetFunctionSourceArgs, GetFunctionSourceResult
from codegraph.repo.port import CodeGraphRepository
from codegraph.source_reader import read_source_range


async def get_function_source(
    repo: CodeGraphRepository, repos_dir: Path, args: GetFunctionSourceArgs
) -> GetFunctionSourceResult:
    detail = await repo.get_node_detail(graph_id=args.graph_id, node_id=args.node_id)
    if detail is None:
        raise ValueError(
            f"Node '{args.node_id}' not found in graph '{args.graph_id}'. "
            f"Call search_nodes first to get a valid node id."
        )
    if detail["kind"] == "file" or not detail.get("path") or detail.get("start_line") is None:
        raise ValueError(
            f"Node '{args.node_id}' is not a function with a known line range. "
            f"Use get_file_content for files, or search_nodes(kind='function') to find a "
            f"function id."
        )
    content, sl, el, truncated = read_source_range(
        repos_dir, args.graph_id, detail["path"], detail["start_line"], detail["end_line"]
    )
    return GetFunctionSourceResult(
        node_id=detail["id"],
        name=detail["name"],
        path=detail["path"],
        start_line=sl,
        end_line=el,
        content=content,
        truncated=truncated,
    )
