"""Co-change coupling read from the on-disk clone's git history.

The graph stores only each file's *last* commit (``File.last_commit_sha``),
not per-commit file sets, and adding ``:Commit`` nodes would be a schema
change the viz spec rules out. So coupling is derived at query time from the
clone that ``codegraph ingest`` already leaves under ``repos_dir`` — the same
external store ``source_reader`` reads from. Read-only, and cached per repo
because walking full history is not something to do on every request.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from codegraph.paths import local_repo_dir

# A sweeping commit (a reformat, a licence header, a dependency bump) touches
# hundreds of unrelated files and would couple all of them to each other. Above
# this width a commit says nothing about design, so it is dropped.
MAX_COMMIT_WIDTH = 60
DEFAULT_MIN_SHARED = 3
_MAX_COMMITS = 5000


@dataclass(frozen=True)
class CoChange:
    a: str
    b: str
    shared: int
    a_commits: int
    b_commits: int

    @property
    def strength(self) -> float:
        """Jaccard: shared commits over commits touching either file."""
        union = self.a_commits + self.b_commits - self.shared
        return self.shared / union if union else 0.0


def parse_log(text: str) -> list[list[str]]:
    """Parse ``git log --name-only`` output into one path list per commit.

    Commits are delimited by a NUL-prefixed header (``--format=%x00%H``) so a
    file named like a sha cannot be mistaken for a commit boundary.
    """
    commits: list[list[str]] = []
    current: list[str] | None = None
    for raw in text.splitlines():
        if raw.startswith("\x00"):
            if current:
                commits.append(current)
            current = []
            continue
        line = raw.strip()
        if line and current is not None:
            current.append(line)
    if current:
        commits.append(current)
    return commits


def commit_counts(commits: list[list[str]], known: set[str]) -> dict[str, int]:
    """How many commits touched each *currently present* file.

    Raw git churn is dominated by files that no longer exist (in the repo this
    was built against, three of the five highest-churn paths were deleted), so
    the live file set is not optional. Unlike coupling, a wide commit still
    counts here: reformatting a file really did change it.
    """
    counts: dict[str, int] = defaultdict(int)
    for files in commits:
        for path in {f for f in files if f in known}:
            counts[path] += 1
    return dict(counts)


def co_change_pairs(
    commits: list[list[str]],
    known: set[str],
    min_shared: int = DEFAULT_MIN_SHARED,
) -> list[CoChange]:
    """Pairs of files that change together, strongest first."""
    touched: dict[str, int] = defaultdict(int)
    together: dict[tuple[str, str], int] = defaultdict(int)
    for files in commits:
        paths = sorted({f for f in files if f in known})
        if len(paths) < 2 or len(paths) > MAX_COMMIT_WIDTH:
            # A one-file commit says nothing about coupling; a huge one lies.
            for p in paths:
                touched[p] += 1
            continue
        for p in paths:
            touched[p] += 1
        for i, a in enumerate(paths):
            for b in paths[i + 1 :]:
                together[(a, b)] += 1

    out = [
        CoChange(a=a, b=b, shared=n, a_commits=touched[a], b_commits=touched[b])
        for (a, b), n in together.items()
        if n >= min_shared
    ]
    out.sort(key=lambda c: (-c.strength, -c.shared, c.a, c.b))
    return out


def read_history(repos_dir: Path, graph_id: str, max_commits: int = _MAX_COMMITS) -> list[list[str]]:
    """Read per-commit file lists from the clone; [] if there is no clone."""
    root = local_repo_dir(graph_id, repos_dir)
    if not (root / ".git").exists():
        return []
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(root), "log",
                f"--max-count={max_commits}",
                "--format=%x00%H", "--name-only", "--no-merges",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return parse_log(proc.stdout)
