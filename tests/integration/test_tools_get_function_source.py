"""get_function_source tool integration test."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _write_clone_file(tmp_path, graph_id: str, file_path: str, content: str):
    safe = graph_id.replace("/", "__")
    abspath = tmp_path / safe / file_path
    abspath.parent.mkdir(parents=True, exist_ok=True)
    abspath.write_text(content)


async def test_get_function_source_returns_body(adapter, fresh_graph_id, tmp_path) -> None:
    rows = await adapter._run_write(
        "CREATE (f:File {graph_id: $gid, path: 'auth.py', language: 'py', deleted: false}) "
        "-[:DEFINES]->(fn:Function {graph_id: $gid, qualified_name: 'login', name: 'login', "
        "kind: 'function', start_line: 2, end_line: 3, path: 'auth.py'}) "
        "RETURN elementId(fn) AS id",
        gid=fresh_graph_id,
    )
    nid = rows[0]["id"]
    _write_clone_file(
        tmp_path, fresh_graph_id, "auth.py", "# header\ndef login():\n    pass\n# footer"
    )

    from codegraph.models.tools import GetFunctionSourceArgs
    from codegraph.tools.get_function_source import get_function_source

    res = await get_function_source(
        adapter, tmp_path, GetFunctionSourceArgs(graph_id=fresh_graph_id, node_id=nid)
    )
    assert res.content == "def login():\n    pass"
    assert res.name == "login"


async def test_get_function_source_rejects_file_node(adapter, fresh_graph_id, tmp_path) -> None:
    rows = await adapter._run_write(
        "CREATE (f:File {graph_id: $gid, path: 'auth.py', language: 'py', deleted: false}) "
        "RETURN elementId(f) AS id",
        gid=fresh_graph_id,
    )
    nid = rows[0]["id"]

    from codegraph.models.tools import GetFunctionSourceArgs
    from codegraph.tools.get_function_source import get_function_source

    with pytest.raises(ValueError, match="not a function"):
        await get_function_source(
            adapter, tmp_path, GetFunctionSourceArgs(graph_id=fresh_graph_id, node_id=nid)
        )


async def test_get_function_source_rejects_tombstoned_defining_file(
    adapter, fresh_graph_id, tmp_path
) -> None:
    rows = await adapter._run_write(
        "CREATE (f:File {graph_id: $gid, path: 'gone.py', language: 'py', deleted: true}) "
        "-[:DEFINES]->(fn:Function {graph_id: $gid, qualified_name: 'ghost', name: 'ghost', "
        "kind: 'function', start_line: 1, end_line: 1, path: 'gone.py'}) "
        "RETURN elementId(fn) AS id",
        gid=fresh_graph_id,
    )
    nid = rows[0]["id"]

    from codegraph.models.tools import GetFunctionSourceArgs
    from codegraph.tools.get_function_source import get_function_source

    with pytest.raises(ValueError, match="not found"):
        await get_function_source(
            adapter, tmp_path, GetFunctionSourceArgs(graph_id=fresh_graph_id, node_id=nid)
        )
