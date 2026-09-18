"""Pure graph_id <-> on-disk clone directory mapping.

No git/network dependency — shared by the ingestion CLI (`ingestion/git.py`,
to know where to clone) and the MCP server's source-reading tools
(`get_file_content`/`get_function_source`, to know where to read from). Both
sides derive the same directory from the same graph_id, since graph_id IS
the repo slug (`repo_slug_from_url(args.url)` in `cli.py`).
"""

from __future__ import annotations

from pathlib import Path


def safe_repo_dirname(graph_id: str) -> str:
    """graph_id ('owner/name') -> filesystem-safe directory name."""
    return graph_id.replace("/", "__")


def local_repo_dir(graph_id: str, repos_dir: Path) -> Path:
    """Resolved local clone directory for a graph_id under repos_dir."""
    return (repos_dir / safe_repo_dirname(graph_id)).resolve()
