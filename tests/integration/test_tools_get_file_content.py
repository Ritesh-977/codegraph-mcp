"""get_file_content tool integration test."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _write_clone_file(tmp_path, graph_id: str, file_path: str, content: str):
    safe = graph_id.replace("/", "__")
    abspath = tmp_path / safe / file_path
    abspath.parent.mkdir(parents=True, exist_ok=True)
    abspath.write_text(content)


async def test_get_file_content_returns_text(adapter, fresh_graph_id, tmp_path) -> None:
    await adapter._run_write(
        "CREATE (f:File {graph_id: $gid, path: 'auth.py', language: 'py', deleted: false})",
        gid=fresh_graph_id,
    )
    _write_clone_file(tmp_path, fresh_graph_id, "auth.py", "def login():\n    pass\n")

    from codegraph.models.tools import GetFileContentArgs
    from codegraph.tools.get_file_content import get_file_content

    res = await get_file_content(
        adapter, tmp_path, GetFileContentArgs(graph_id=fresh_graph_id, file_path="auth.py")
    )
    assert res.content == "def login():\n    pass"
    assert res.language == "py"


async def test_get_file_content_slices_range(adapter, fresh_graph_id, tmp_path) -> None:
    await adapter._run_write(
        "CREATE (f:File {graph_id: $gid, path: 'a.py', language: 'py', deleted: false})",
        gid=fresh_graph_id,
    )
    _write_clone_file(tmp_path, fresh_graph_id, "a.py", "one\ntwo\nthree\nfour")

    from codegraph.models.tools import GetFileContentArgs
    from codegraph.tools.get_file_content import get_file_content

    res = await get_file_content(
        adapter,
        tmp_path,
        GetFileContentArgs(graph_id=fresh_graph_id, file_path="a.py", start_line=2, end_line=3),
    )
    assert res.content == "two\nthree"


async def test_get_file_content_rejects_deleted_file(adapter, fresh_graph_id, tmp_path) -> None:
    await adapter._run_write(
        "CREATE (f:File {graph_id: $gid, path: 'gone.py', language: 'py', deleted: true})",
        gid=fresh_graph_id,
    )
    _write_clone_file(tmp_path, fresh_graph_id, "gone.py", "stale content")

    from codegraph.models.tools import GetFileContentArgs
    from codegraph.tools.get_file_content import get_file_content

    with pytest.raises(ValueError, match="not found"):
        await get_file_content(
            adapter, tmp_path, GetFileContentArgs(graph_id=fresh_graph_id, file_path="gone.py")
        )


async def test_get_file_content_missing_on_disk_raises(adapter, fresh_graph_id, tmp_path) -> None:
    await adapter._run_write(
        "CREATE (f:File {graph_id: $gid, path: 'ghost.py', language: 'py', deleted: false})",
        gid=fresh_graph_id,
    )
    # No file written to the fake clone — graph says it exists, disk doesn't.

    from codegraph.models.tools import GetFileContentArgs
    from codegraph.tools.get_file_content import get_file_content

    with pytest.raises(ValueError, match="No local clone found"):
        await get_file_content(
            adapter, tmp_path, GetFileContentArgs(graph_id=fresh_graph_id, file_path="ghost.py")
        )
