"""E2e: verify the server has all 6 tools registered and callable structure is correct.

This test doesn't need a running Neo4j — it verifies the server's tool registry
structure, not actual tool execution. It uses the FastMCP internal API to inspect
registered tools without starting the server.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow


def test_all_six_tools_registered() -> None:
    """The server must have all 6 tools registered."""
    from codegraph.server import mcp

    tm = getattr(mcp, "_tool_manager", None)
    if tm is None:
        pytest.skip("tool manager not accessible in this FastMCP version")
    names = set(getattr(tm, "_tools", {}).keys())
    expected = {
        "list_repos",
        "init_repository_node",
        "get_repo_structure",
        "find_file_dependencies",
        "search_nodes",
        "get_node_detail",
    }
    assert expected == names, f"tool mismatch: extra={names - expected}, missing={expected - names}"


def test_resources_registered() -> None:
    """The server must have the 2 resources registered (one plain, one template)."""
    from codegraph.server import mcp

    rm = getattr(mcp, "_resource_manager", None)
    if rm is None:
        pytest.skip("resource manager not accessible in this FastMCP version")
    resources = getattr(rm, "_resources", {})
    templates = getattr(rm, "_templates", {})
    uris = set(resources.keys()) | set(templates.keys())
    assert "codegraph://repos" in uris, f"missing codegraph://repos; found: {uris}"
    assert any("schema" in u for u in uris), (
        f"missing schema template resource; found: {uris}"
    )
    assert len(uris) >= 2, f"expected 2 resources registered, found: {uris}"


def test_tool_descriptions_are_llm_readable() -> None:
    """Each tool must have a non-empty description (the LLM reads this)."""
    from codegraph.server import mcp

    tm = getattr(mcp, "_tool_manager", None)
    if tm is None:
        pytest.skip("tool manager not accessible")
    tools = getattr(tm, "_tools", {})
    for name, tool in tools.items():
        desc = getattr(tool, "description", None) or ""
        assert len(desc) > 20, f"tool '{name}' has no meaningful description: {desc!r}"
