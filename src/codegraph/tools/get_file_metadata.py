"""get_file_metadata tool — who last touched a file, and when.

Answers the triage questions ("who owns this?", "is this stale?") from the
commit data ingest records on each File node.
"""

from __future__ import annotations

from codegraph.models.tools import GetFileMetadataArgs, GetFileMetadataResult
from codegraph.repo.port import CodeGraphRepository


async def get_file_metadata(
    repo: CodeGraphRepository, args: GetFileMetadataArgs
) -> GetFileMetadataResult:
    info = await repo.get_file_info(graph_id=args.graph_id, file_path=args.file_path)
    if info is None:
        raise ValueError(
            f"File '{args.file_path}' not found in graph '{args.graph_id}' (or has been "
            f"deleted). Use get_repo_structure to confirm the path exists."
        )
    return GetFileMetadataResult(
        path=info["path"],
        language=info.get("language"),
        last_author=info.get("last_author"),
        last_commit_at=info.get("last_commit_at"),
        last_commit_sha=info.get("last_commit_sha"),
    )
