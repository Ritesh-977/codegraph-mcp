"""git log output parser — pure logic."""

from __future__ import annotations

from codegraph.ingestion.commits import parse_log_output

# Real `git log --name-only` output puts a BLANK LINE between a commit's header
# and its file list. The original fixture omitted it, so the parser's
# blank-line block splitting passed here while returning zero entries against
# actual git — every ingested file had no author/date/sha.
_LOG = """abc1230|Alice|2026-07-20T10:00:00+00:00

src/auth.py
src/main.py

def4560|Bob|2026-07-19T09:00:00+00:00

README.md
"""

# Compact form (no blank line) must keep working too.
_LOG_COMPACT = """abc1230|Alice|2026-07-20T10:00:00+00:00
src/auth.py
src/main.py

def4560|Bob|2026-07-19T09:00:00+00:00
README.md
"""


def test_parses_real_git_format_with_blank_line_after_header() -> None:
    info = parse_log_output(_LOG)
    assert set(info) == {"src/auth.py", "src/main.py", "README.md"}
    assert info["src/auth.py"].last_author == "Alice"
    assert info["README.md"].last_author == "Bob"


def test_parses_compact_format_too() -> None:
    info = parse_log_output(_LOG_COMPACT)
    assert info["src/auth.py"].last_author == "Alice"
    assert info["README.md"].last_author == "Bob"


def test_path_containing_pipe_is_not_mistaken_for_a_header() -> None:
    log = "abc1230|Alice|2026-07-20T10:00:00+00:00\n\nweird|name|file.py\n"
    info = parse_log_output(log)
    assert "weird|name|file.py" in info


def test_parses_per_file_last_author() -> None:
    info = parse_log_output(_LOG)
    assert info["src/auth.py"].last_author == "Alice"
    assert info["src/main.py"].last_author == "Alice"
    assert info["README.md"].last_author == "Bob"


def test_last_commit_sha_captured() -> None:
    info = parse_log_output(_LOG)
    assert info["src/auth.py"].last_commit_sha == "abc1230"
    assert info["README.md"].last_commit_sha == "def4560"


def test_empty_log_returns_empty() -> None:
    assert parse_log_output("") == {}
