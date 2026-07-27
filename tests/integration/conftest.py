"""Pytest configuration shared across all test layers."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _have_testcontainers() -> bool:
    try:
        import testcontainers  # noqa: F401
    except Exception:
        return False
    return True


@pytest.fixture()
def neo4j_env() -> dict[str, str] | None:
    """Return neo4j connection env if a live instance is available, else None."""
    uri = os.environ.get("NEO4J_URI")
    if uri:
        return {
            "NEO4J_URI": uri,
            "NEO4J_USER": os.environ.get("NEO4J_USER", "neo4j"),
            "NEO4J_PASSWORD": os.environ.get("NEO4J_PASSWORD", "changeme123"),
            "NEO4J_DB": os.environ.get("NEO4J_DB", "neo4j"),
            "REPOS_DIR": os.environ.get("REPOS_DIR", "./repos"),
        }
    if not _have_testcontainers():
        pytest.skip("No NEO4J_URI and testcontainers not installed")
    from testcontainers.neo4j import Neo4jContainer

    with Neo4jContainer("neo4j:5-community") as container:
        yield {
            "NEO4J_URI": container.get_connection_url(),
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": container.settings.password,
            "NEO4J_DB": "neo4j",
            "REPOS_DIR": "./repos",
        }


@pytest.fixture()
async def adapter(neo4j_env: dict[str, str] | None):  # type: ignore[no-untyped-def]
    if neo4j_env is None:
        pytest.skip("no neo4j")
    from codegraph.repo.neo4j_adapter import Neo4jAdapter

    from codegraph.config import Settings

    s = Settings(**neo4j_env)
    ad = Neo4jAdapter.from_settings(s)
    await ad.connect()
    await ad.apply_migrations()
    yield ad
    await ad.close()


@pytest.fixture()
def fresh_graph_id() -> str:
    return f"test-{uuid.uuid4()}"
