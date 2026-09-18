"""codegraph-viz settings surface."""

from __future__ import annotations

from codegraph.config import Settings


def test_viz_defaults() -> None:
    s = Settings()
    assert s.viz_host == "127.0.0.1"
    assert s.viz_port == 8787


def test_viz_overridable_via_env(monkeypatch) -> None:
    monkeypatch.setenv("VIZ_HOST", "0.0.0.0")
    monkeypatch.setenv("VIZ_PORT", "9090")
    s = Settings()
    assert s.viz_host == "0.0.0.0"
    assert s.viz_port == 9090
