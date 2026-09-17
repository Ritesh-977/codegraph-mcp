"""Co-change coupling from git history."""

from __future__ import annotations

from codegraph.viz.churn import CoChange, co_change_pairs, parse_log

LOG = "\n".join([
    "\x00c1",
    "a.py",
    "b.py",
    "",
    "\x00c2",
    "a.py",
    "b.py",
    "",
    "\x00c3",
    "a.py",
    "b.py",
    "c.py",
    "",
    "\x00c4",
    "c.py",
    "",
])


def test_parse_log_groups_files_per_commit() -> None:
    commits = parse_log(LOG)
    assert commits == [["a.py", "b.py"], ["a.py", "b.py"], ["a.py", "b.py", "c.py"], ["c.py"]]


def test_co_change_counts_pairs_and_ignores_singletons() -> None:
    pairs = co_change_pairs(parse_log(LOG), known={"a.py", "b.py", "c.py"}, min_shared=2)
    assert pairs[0] == CoChange(a="a.py", b="b.py", shared=3, a_commits=3, b_commits=3)
    # a/c and b/c share only one commit, below min_shared
    assert all(p.shared >= 2 for p in pairs)


def test_unknown_paths_are_dropped() -> None:
    """Deleted or never-ingested files must not appear as phantom coupling."""
    pairs = co_change_pairs(parse_log(LOG), known={"a.py"}, min_shared=1)
    assert pairs == []


def test_huge_commits_are_ignored_as_noise() -> None:
    """A 400-file reformat commit couples everything to everything."""
    wide = [[f"f{i}.py" for i in range(400)]]
    assert co_change_pairs(wide, known={f"f{i}.py" for i in range(400)}, min_shared=1) == []


def test_pairs_sorted_by_strength() -> None:
    log = [["a", "b"], ["a", "b"], ["a", "b"], ["c", "d"], ["c", "d"]]
    pairs = co_change_pairs(log, known={"a", "b", "c", "d"}, min_shared=2)
    assert [(p.a, p.b, p.shared) for p in pairs] == [("a", "b", 3), ("c", "d", 2)]
