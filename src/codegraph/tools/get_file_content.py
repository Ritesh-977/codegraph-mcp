"""get_file_content tool — return real source text for a file, honoring the
deleted tombstone. Reads from the on-disk clone `repos_dir` already holds
(see design doc §2.1) — the server never clones or writes, only reads."""

from __future__ import annotations

from pathlib import Path

from codegraph.models.tools import GetFileContentArgs, GetFileContentResult
from codegraph.repo.port import CodeGraphRepository
from codegraph.source_reader import read_source_range


async def get_file_content(
    repo: CodeGraphRepository, repos_dir: Path, args: GetFileContentArgs
) -> GetFileContentResult:
    info = await repo.get_file_info(graph_id=args.graph_id, file_path=args.file_path)
    if info is None:
        raise ValueError(
            f"File '{args.file_path}' not found in graph '{args.graph_id}' (or has been "
            f"deleted). Use get_repo_structure to confirm the path exists."
        )
    content, sl, el, truncated = read_source_range(
        repos_dir, args.graph_id, args.file_path, args.start_line, args.end_line
    )
    return GetFileContentResult(
        path=info["path"],
        language=info.get("language"),
        content=content,
        start_line=sl,
        end_line=el,
        truncated=truncated,
    )
