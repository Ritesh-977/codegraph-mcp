"""One-pass git log → per-file last author/date/sha."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from git import Repo

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class CommitInfo:
    last_commit_sha: str
    last_author: str
    last_commit_at: str


def parse_log_output(text: str) -> dict[str, CommitInfo]:
    """Parse `git log --format='%H|%an|%aI' --name-only` output.

    Parsed line-by-line rather than by splitting on blank lines: real git output
    puts a blank line *between* a commit's header and its file list, so
    block-splitting separates each header from its own files and yields nothing.
    A header is identified by its leading commit sha, which a path can't
    plausibly imitate.
    """
    out: dict[str, CommitInfo] = {}
    sha = author = date = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("|", maxsplit=2)
        if len(parts) == 3 and _SHA_RE.match(parts[0]):
            sha, author, date = parts
            continue
        if sha is not None and line not in out:  # first occurrence = most recent
            out[line] = CommitInfo(
                last_commit_sha=sha, last_author=author or "", last_commit_at=date or ""
            )
    return out


def collect_commits(repo_root: Path) -> dict[str, CommitInfo]:
    repo = Repo(str(repo_root))
    out = repo.git.log("--format=%H|%an|%aI", "--name-only")
    return parse_log_output(out)
