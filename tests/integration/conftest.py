"""Pytest configuration shared across all test layers."""

from __future__ import annotations

import contextlib
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


def _docker_daemon_reachable() -> bool:
    """Cheap probe: is a Docker daemon reachable from the Python SDK?

    The docker CLI context may point at a named pipe that isn't actually
    listening yet (Docker Desktop not started). Skip integration tests in
    that case rather than erroring mid-fixture.
    """
    try:
        import docker
    except Exception:
        return False
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def neo4j_env():  # type: ignore[no-untyped-def]
    """Return neo4j connection env if a live instance is available, else skip.

    Resolution order: (1) NEO4J_URI env var already set (manual `docker compose up`);
    (2) testcontainer spun up ad-hoc — only if Docker daemon is reachable.
    Skips cleanly if neither path works, so `make test` stays green without Docker.

    Session-scoped on purpose: Neo4j is a heavyweight JVM boot (~30-40s), so a
    container per test made the suite take ~22 minutes and starved later
    containers into 120s startup timeouts. One container serves the whole
    session; per-test isolation comes from `fresh_graph_id` + the `adapter`
    fixture wiping that namespace on teardown.
    """
    uri = os.environ.get("NEO4J_URI")
    if uri:
        return {
            "NEO4J_URI": uri,
            "NEO4J_USER": os.environ.get("NEO4J_USER", "neo4j"),
            "NEO4J_PASSWORD": os.environ.get("NEO4J_PASSWORD", "changeme123"),
            "NEO4J_DB": os.environ.get("NEO4J_DB", "neo4j"),
            "REPOS_DIR": os.environ.get("REPOS_DIR", "./repos"),
        }
    if not _have_testcontainers() or not _docker_daemon_reachable():
        pytest.skip("No NEO4J_URI and Docker daemon not reachable")
    from testcontainers.neo4j import Neo4jContainer

    with Neo4jContainer("neo4j:5-community") as container:
        yield {
            "NEO4J_URI": container.get_connection_url(),
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": container.password,
            "NEO4J_DB": "neo4j",
            "REPOS_DIR": "./repos",
        }


@pytest.fixture()
async def adapter(neo4j_env: dict[str, str] | None, fresh_graph_id: str):  # type: ignore[no-untyped-def]
    if neo4j_env is None:
        pytest.skip("no neo4j")
    from codegraph.config import Settings
    from codegraph.repo.neo4j_adapter import Neo4jAdapter

    # Settings' fields are lowercase (neo4j_uri, ...) but neo4j_env's keys are
    # uppercase env-var-style names; pydantic matches constructor kwargs by
    # exact field name (not env-var aliasing, which only applies to actual
    # os.environ/.env loading), so passing the dict as-is silently no-ops
    # every override (extra="ignore" swallows the mismatch) and falls back
    # to .env's bolt://localhost:7687 — never the ephemeral test container.
    s = Settings(**{k.lower(): v for k, v in neo4j_env.items()})
    ad = Neo4jAdapter.from_settings(s)
    await ad.connect()
    await ad.apply_migrations()
    yield ad
    # The container is session-scoped, so wipe this test's graph_id namespace
    # rather than leaking it into every later test (list_repos, for one, is
    # deliberately unfiltered by graph_id and would otherwise see it).
    with contextlib.suppress(Exception):
        await ad.soft_cleanup(fresh_graph_id)
    await ad.close()


@pytest.fixture()
def fresh_graph_id() -> str:
    return f"test-{uuid.uuid4()}"
