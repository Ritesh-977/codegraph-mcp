"""Reads source text from the on-disk repo clone that `codegraph ingest`
already leaves under `repos_dir` — the "external store" for Phase 2 source
retrieval (see design doc §2.1). The graph holds pointers (`File.path`,
`Function.start_line`/`end_line`); this module resolves those pointers to
actual file bytes. Read-only: the server never writes here.
"""

from __future__ import annotations

from pathlib import Path

from codegraph.paths import local_repo_dir

DEFAULT_MAX_LINES = 2000


def read_source_range(
    repos_dir: Path,
    graph_id: str,
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_lines: int = DEFAULT_MAX_LINES,
) -> tuple[str, int, int, bool]:
    """Return (content, resolved_start_line, resolved_end_line, truncated).

    `start_line`/`end_line` are 1-indexed and inclusive; omit either (or
    both) for the whole file. Raises ValueError if `file_path` resolves
    outside the repo's clone root, the on-disk clone doesn't have the file,
    or the requested range is invalid.
    """
    base = local_repo_dir(graph_id, repos_dir)
    candidate = (base / file_path).resolve()
    # Check containment on the *resolved* path rather than pre-validating the
    # input string: `Path(base) / "/absolute/path"` silently discards `base`
    # in pathlib, and a symlink inside the clone could point outside it —
    # resolving first and checking containment on the result catches both.
    if not (candidate == base or candidate.is_relative_to(base)):
        raise ValueError(f"file_path {file_path!r} resolves outside the repository root")
    if not candidate.is_file():
        raise ValueError(
            f"No local clone found for '{graph_id}' at '{file_path}'. "
            f"Run `codegraph ingest --force` to refresh the on-disk clone."
        )
    lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    if total == 0:
        return "", 1, 0, False
    sl = max(1, start_line or 1)
    el = min(total, end_line or total)
    if sl > el:
        raise ValueError(f"start_line {sl} is after end_line {el} (file has {total} lines)")
    selected = lines[sl - 1 : el]
    truncated = False
    if len(selected) > max_lines:
        selected = selected[:max_lines]
        el = sl + max_lines - 1
        truncated = True
    return "\n".join(selected), sl, el, truncated
