"""git ops — pure-logic URL parsing; live clone is slow-marked."""

from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from codegraph.ingestion.git import clone_or_fetch, local_path_for, repo_slug_from_url


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/owner/name.git", "github.com/owner/name"),
    ("https://github.com/owner/name", "github.com/owner/name"),
    ("git@github.com:owner/name.git", "github.com/owner/name"),
    ("https://gitlab.com/group/sub/proj.git", "gitlab.com/group/sub/proj"),
    # Self-hosted hosts must stay distinct — the whole point of qualifying by host.
    ("https://git.corp.internal/acme/app.git", "git.corp.internal/acme/app"),
])
def test_slug_from_url(url: str, expected: str) -> None:
    assert repo_slug_from_url(url) == expected


def test_same_path_on_different_hosts_does_not_collide() -> None:
    """Without the host, github.com/acme/app and gitlab.com/acme/app would
    merge into one graph — silent data corruption rather than a loud failure."""
    assert repo_slug_from_url("https://github.com/acme/app") != repo_slug_from_url(
        "https://gitlab.com/acme/app"
    )


def test_local_path_uses_repos_dir_and_safe_name() -> None:
    p = local_path_for("https://github.com/owner/name.git", Path("./repos"))
    assert p.parent == Path("./repos").resolve()
    assert "owner" in p.name and "name" in p.name


def test_clone_or_fetch_force_removes_stale_cache_and_reclones(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "repo"
    pack_dir = dest / ".git" / "objects" / "pack"
    pack_dir.mkdir(parents=True)
    marker = dest / "stale.txt"
    marker.write_text("old clone content")
    # Git marks pack files read-only; on Windows that makes a naive
    # shutil.rmtree fail with PermissionError (WinError 5).
    readonly_pack = pack_dir / "pack-deadbeef.idx"
    readonly_pack.write_text("pack data")
    readonly_pack.chmod(stat.S_IREAD)

    clone_calls: list[tuple[str, str, str | None]] = []

    class _FakeRepo:
        head = SimpleNamespace(ref=SimpleNamespace(name="main"))

    class _FakeRepoCls:
        @staticmethod
        def clone_from(url: str, dest: str, depth: int | None = None, branch: str | None = None) -> _FakeRepo:
            clone_calls.append((url, dest, branch))
            Path(dest).mkdir(parents=True, exist_ok=True)
            return _FakeRepo()

        def __call__(self, path: str) -> _FakeRepo:  # pragma: no cover - fetch path, unused here
            raise AssertionError("fetch+reset path should not run when force=True")

    monkeypatch.setattr("codegraph.ingestion.git.Repo", _FakeRepoCls())

    branch = clone_or_fetch(
        "https://github.com/owner/name.git", dest, branch=None, depth=1, force=True
    )

    assert not marker.exists()  # stale cache was removed
    assert len(clone_calls) == 1  # fresh-clone path was taken, not fetch+reset
    assert branch == "main"
