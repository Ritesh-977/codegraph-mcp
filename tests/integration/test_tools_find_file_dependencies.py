"""find_file_dependencies tool integration test."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_find_deps_returns_imported_by(adapter, fresh_graph_id) -> None:
    await adapter._run_write(
        "CREATE (r:Repository {graph_id: $gid}) "
        "-[:CONTAINS]->(auth:File {graph_id: $gid, path: 'auth.py', language: 'py', deleted: false}), "
        "(r)-[:CONTAINS]->(us:File {graph_id: $gid, path: 'user_service.py', language: 'py', deleted: false}) "
        "WITH r, auth, us MERGE (us)-[:IMPORTS]->(auth)",
        gid=fresh_graph_id,
    )
    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res = await find_file_dependencies(
        adapter, FindFileDependenciesArgs(graph_id=fresh_graph_id, file_path="auth.py")
    )
    paths = [e.path for e in res.imported_by]
    assert "user_service.py" in paths


async def _make_import_chain(adapter, gid: str) -> None:
    """a.py -IMPORTS-> b.py -IMPORTS-> c.py, all live."""
    await adapter._run_write(
        "CREATE (a:File {graph_id: $gid, path: 'a.py', language: 'py', deleted: false}), "
        "(b:File {graph_id: $gid, path: 'b.py', language: 'py', deleted: false}), "
        "(c:File {graph_id: $gid, path: 'c.py', language: 'py', deleted: false}) "
        "MERGE (a)-[:IMPORTS]->(b) MERGE (b)-[:IMPORTS]->(c)",
        gid=gid,
    )


async def _make_call_chain(adapter, gid: str) -> None:
    """source.py DEFINES fn1 -CALLS-> fn2 -CALLS-> fn3 DEFINES target.py."""
    await adapter._run_write(
        "CREATE (sf:File {graph_id: $gid, path: 'source.py', language: 'py', deleted: false}), "
        "(tf:File {graph_id: $gid, path: 'target.py', language: 'py', deleted: false}), "
        "(fn1:Function {graph_id: $gid, qualified_name: 'fn1', name: 'fn1', kind: 'function'}), "
        "(fn2:Function {graph_id: $gid, qualified_name: 'fn2', name: 'fn2', kind: 'function'}), "
        "(fn3:Function {graph_id: $gid, qualified_name: 'fn3', name: 'fn3', kind: 'function'}) "
        "MERGE (sf)-[:DEFINES]->(fn1) MERGE (tf)-[:DEFINES]->(fn3) "
        "MERGE (fn1)-[:CALLS]->(fn2) MERGE (fn2)-[:CALLS]->(fn3)",
        gid=gid,
    )


async def test_find_deps_imported_by_multi_hop(adapter, fresh_graph_id) -> None:
    await _make_import_chain(adapter, fresh_graph_id)
    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path="c.py", direction="imported_by", max_hops=2
        ),
    )
    hops = {e.path: e.hop for e in res.imported_by}
    assert hops == {"b.py": 1, "a.py": 2}


async def test_find_deps_imports_multi_hop(adapter, fresh_graph_id) -> None:
    await _make_import_chain(adapter, fresh_graph_id)
    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path="a.py", direction="imports", max_hops=2
        ),
    )
    hops = {e.path: e.hop for e in res.imports}
    assert hops == {"b.py": 1, "c.py": 2}


async def test_find_deps_max_hops_limits_depth(adapter, fresh_graph_id) -> None:
    await _make_import_chain(adapter, fresh_graph_id)
    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path="c.py", direction="imported_by", max_hops=1
        ),
    )
    paths = {e.path for e in res.imported_by}
    assert paths == {"b.py"}


async def test_find_deps_max_hops_zero_returns_empty(adapter, fresh_graph_id) -> None:
    await _make_import_chain(adapter, fresh_graph_id)
    # Unresolved symbol import — must still show up in external_symbols at max_hops=0.
    await adapter._run_write(
        "MATCH (a:File {graph_id: $gid, path: 'a.py'}) "
        "MERGE (a)-[:IMPORTS]->(:Symbol {graph_id: $gid, name: 'os', kind: 'import'})",
        gid=fresh_graph_id,
    )
    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path="a.py", direction="both", max_hops=0
        ),
    )
    assert res.imported_by == []
    assert res.imports == []
    assert res.callers == []
    assert res.calls == []
    assert any(s.name == "os" for s in res.external_symbols)


async def test_find_deps_deleted_intermediate_breaks_chain(adapter, fresh_graph_id) -> None:
    await adapter._run_write(
        "CREATE (a:File {graph_id: $gid, path: 'a.py', language: 'py', deleted: false}), "
        "(b:File {graph_id: $gid, path: 'b.py', language: 'py', deleted: true}), "
        "(c:File {graph_id: $gid, path: 'c.py', language: 'py', deleted: false}) "
        "MERGE (a)-[:IMPORTS]->(b) MERGE (b)-[:IMPORTS]->(c)",
        gid=fresh_graph_id,
    )
    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path="c.py", direction="imported_by", max_hops=2
        ),
    )
    assert res.imported_by == []


async def test_find_deps_diamond_dedup_takes_min_hop(adapter, fresh_graph_id) -> None:
    await adapter._run_write(
        "CREATE (a:File {graph_id: $gid, path: 'a.py', language: 'py', deleted: false}), "
        "(m:File {graph_id: $gid, path: 'm.py', language: 'py', deleted: false}), "
        "(x:File {graph_id: $gid, path: 'x.py', language: 'py', deleted: false}) "
        "MERGE (a)-[:IMPORTS]->(x) MERGE (a)-[:IMPORTS]->(m) MERGE (m)-[:IMPORTS]->(x)",
        gid=fresh_graph_id,
    )
    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path="x.py", direction="imported_by", max_hops=2
        ),
    )
    a_entries = [e for e in res.imported_by if e.path == "a.py"]
    assert len(a_entries) == 1
    assert a_entries[0].hop == 1


async def test_find_deps_callers_multi_hop(adapter, fresh_graph_id) -> None:
    await _make_call_chain(adapter, fresh_graph_id)
    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path="target.py", direction="imported_by", max_hops=2
        ),
    )
    hops = {e.path: e.hop for e in res.callers}
    assert hops == {"fn2": 1, "fn1": 2}


async def test_find_deps_external_symbols_gated_by_direction(adapter, fresh_graph_id) -> None:
    await adapter._run_write(
        "CREATE (a:File {graph_id: $gid, path: 'a.py', language: 'py', deleted: false}) "
        "MERGE (a)-[:IMPORTS]->(:Symbol {graph_id: $gid, name: 'os', kind: 'import'})",
        gid=fresh_graph_id,
    )
    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res_imported_by = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path="a.py", direction="imported_by", max_hops=1
        ),
    )
    assert res_imported_by.external_symbols == []

    res_imports = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path="a.py", direction="imports", max_hops=1
        ),
    )
    assert any(s.name == "os" for s in res_imports.external_symbols)


async def test_find_deps_calls_multi_hop(adapter, fresh_graph_id) -> None:
    await _make_call_chain(adapter, fresh_graph_id)
    from codegraph.models.tools import FindFileDependenciesArgs
    from codegraph.tools.find_file_dependencies import find_file_dependencies

    res = await find_file_dependencies(
        adapter,
        FindFileDependenciesArgs(
            graph_id=fresh_graph_id, file_path="source.py", direction="imports", max_hops=2
        ),
    )
    hops = {e.path: e.hop for e in res.calls}
    assert hops == {"fn2": 1, "fn3": 2}
