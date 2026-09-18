"""source_reader — reads source text from the on-disk repo clone. Pure
filesystem logic, no Neo4j needed."""

from __future__ import annotations

import pytest

from codegraph.source_reader import read_source_range


def _seed_repo(tmp_path, graph_id: str, file_path: str, content: str):
    safe = graph_id.replace("/", "__")
    abspath = tmp_path / safe / file_path
    abspath.parent.mkdir(parents=True, exist_ok=True)
    abspath.write_text(content)
    return abspath


def test_read_source_range_full_file(tmp_path) -> None:
    _seed_repo(tmp_path, "o/n", "src/auth.py", "line1\nline2\nline3")

    content, sl, el, truncated = read_source_range(tmp_path, "o/n", "src/auth.py")

    assert content == "line1\nline2\nline3"
    assert (sl, el, truncated) == (1, 3, False)


def test_read_source_range_slices_lines(tmp_path) -> None:
    _seed_repo(tmp_path, "o/n", "src/auth.py", "line1\nline2\nline3\nline4")

    content, sl, el, truncated = read_source_range(tmp_path, "o/n", "src/auth.py", 2, 3)

    assert content == "line2\nline3"
    assert (sl, el, truncated) == (2, 3, False)


def test_read_source_range_rejects_path_traversal(tmp_path) -> None:
    _seed_repo(tmp_path, "o/n", "src/auth.py", "safe")
    (tmp_path / "secret.txt").write_text("outside the clone")

    with pytest.raises(ValueError, match="outside the repository root"):
        read_source_range(tmp_path, "o/n", "../secret.txt")


def test_read_source_range_rejects_absolute_path_escape(tmp_path) -> None:
    # Path(base) / "/abs/path" silently discards `base` in pathlib — the
    # post-resolve containment check must still catch this.
    _seed_repo(tmp_path, "o/n", "src/auth.py", "safe")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("nope")

    with pytest.raises(ValueError, match="outside the repository root"):
        read_source_range(tmp_path, "o/n", str(outside))


def test_read_source_range_missing_file_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="No local clone found"):
        read_source_range(tmp_path, "o/n", "does_not_exist.py")


def test_read_source_range_truncates(tmp_path) -> None:
    content = "\n".join(f"line{i}" for i in range(10))
    _seed_repo(tmp_path, "o/n", "big.py", content)

    text, sl, el, truncated = read_source_range(tmp_path, "o/n", "big.py", max_lines=3)

    assert text == "line0\nline1\nline2"
    assert (sl, el, truncated) == (1, 3, True)


def test_read_source_range_invalid_range_raises(tmp_path) -> None:
    _seed_repo(tmp_path, "o/n", "small.py", "line1\nline2")

    with pytest.raises(ValueError, match="is after"):
        read_source_range(tmp_path, "o/n", "small.py", start_line=2, end_line=1)


def test_read_source_range_empty_file(tmp_path) -> None:
    _seed_repo(tmp_path, "o/n", "empty.py", "")

    content, sl, el, truncated = read_source_range(tmp_path, "o/n", "empty.py")

    assert (content, sl, el, truncated) == ("", 1, 0, False)
