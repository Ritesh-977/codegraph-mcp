"""CLI dispatch — subcommand routing, no I/O of its own."""

from __future__ import annotations

from codegraph.cli import main


def test_cli_no_args_prints_help_to_stderr(capsys: object) -> None:  # type: ignore[no-untyped-def]
    rc = main([])
    assert rc == 0
    out = capsys.readouterr()  # type: ignore[no-untyped-def]
    assert "codegraph" in out.err.lower() or "usage" in out.err.lower()


def test_cli_version() -> None:
    assert main(["--version"]) == 0


def test_cli_ingest_requires_url(capsys: object) -> None:  # type: ignore[no-untyped-def]
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["ingest"])
    assert exc.value.code == 2  # argparse missing-required-arg exit code


def test_cli_ingest_without_neo4j_returns_1(capsys: object) -> None:  # type: ignore[no-untyped-def]
    # Ingest is now wired — without a running Neo4j it fails fast at connect()
    # and returns 1. This proves the code path is live (past the old stub).
    rc = main(["ingest", "https://github.com/o/n"])
    assert rc == 1
    out = capsys.readouterr()  # type: ignore[no-untyped-def]
    assert "ingest failed" in out.err


def test_cli_serve_stub_returns_2(capsys: object) -> None:  # type: ignore[no-untyped-def]
    rc = main(["serve"])
    assert rc == 2


def test_cli_reset_requires_graph_id(capsys: object) -> None:  # type: ignore[no-untyped-def]
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["reset"])
    assert exc.value.code == 2


def test_cli_ls_stub_returns_2(capsys: object) -> None:  # type: ignore[no-untyped-def]
    rc = main(["ls"])
    assert rc == 2
