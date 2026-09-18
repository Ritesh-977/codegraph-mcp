"""CLI dispatch — subcommand routing + ingest orchestration."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="codegraph",
        description="Knowledge-Graph MCP Server for GitHub repos",
    )
    p.add_argument("--version", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    ing = sub.add_parser("ingest", help="Clone + parse + load a GitHub repo into Neo4j")
    ing.add_argument("url", help="GitHub repo URL")
    ing.add_argument("--branch", default=None, help="Branch to ingest (default: repo default)")
    ing.add_argument("--force", action="store_true", help="Re-clone even if cached")

    sub.add_parser("serve", help="Run the MCP server (stdio transport)")

    rst = sub.add_parser("reset", help="Hard-wipe one repo from Neo4j (destructive)")
    rst.add_argument("--graph-id", required=True)
    rst.add_argument(
        "--keep-clone",
        action="store_true",
        help="Keep the on-disk clone cache (by default reset removes it too)",
    )

    sub.add_parser("ls", help="List ingested repos in Neo4j")

    viz = sub.add_parser("viz", help="Run the local web UI (browser graph viewer)")
    viz.add_argument("--host", default=None, help="Bind host (default: Settings.viz_host)")
    viz.add_argument(
        "--port", type=int, default=None, help="Bind port (default: Settings.viz_port)"
    )
    return p


def _cmd_serve() -> int:
    from codegraph.server import serve
    return serve()


def _cmd_ls() -> int:
    import asyncio

    from codegraph.config import Settings
    from codegraph.repo.neo4j_adapter import Neo4jAdapter

    async def _go() -> int:
        s = Settings()
        ad = Neo4jAdapter.from_settings(s)
        try:
            await ad.connect()
            repos = await ad.list_repos()
            for r in repos:
                print(f"{r['graph_id']}\t{r.get('url', '')}")
        finally:
            with contextlib.suppress(Exception):
                await ad.close()
        return 0

    try:
        return asyncio.run(_go())
    except Exception as exc:
        print(f"ls failed: {exc}", file=sys.stderr)
        return 1


def _cmd_viz(args: argparse.Namespace) -> int:
    """Serve the read-only web UI. A separate process from `codegraph serve`,
    so the MCP server's stdout stays pure JSON-RPC."""
    import uvicorn

    from codegraph.config import Settings
    from codegraph.viz.api import create_app

    s = Settings()
    app = create_app(s)
    uvicorn.run(
        app,
        host=args.host or s.viz_host,
        port=args.port or s.viz_port,
        log_level="info",
    )
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    import asyncio

    from codegraph.config import Settings
    from codegraph.repo.neo4j_adapter import Neo4jAdapter

    async def _go() -> int:
        s = Settings()
        ad = Neo4jAdapter.from_settings(s)
        try:
            await ad.connect()
            await ad.soft_cleanup(args.graph_id)
            print(f"wiped graph_id={args.graph_id}", file=sys.stderr)
            if not args.keep_clone:
                _remove_clone(s.repos_dir, args.graph_id)
        except Exception as ex:
            print(f"reset failed: {ex}", file=sys.stderr)
            return 1
        finally:
            with contextlib.suppress(Exception):
                await ad.close()
        return 0

    return asyncio.run(_go())


def _remove_clone(repos_dir: Path, graph_id: str) -> None:
    """Delete the cached clone for a graph_id (6.4 ops hygiene).

    Reset previously wiped Neo4j but left the working tree on disk, so the
    cache silently grew and a "reset" repo still had stale files sitting there.
    """
    from codegraph.ingestion.git import _force_remove_tree
    from codegraph.paths import local_repo_dir

    dest = local_repo_dir(graph_id, repos_dir)
    if not dest.exists():
        print(f"no clone cache at {dest}", file=sys.stderr)
        return
    try:
        _force_remove_tree(dest)
        print(f"removed clone cache {dest}", file=sys.stderr)
    except Exception as ex:
        print(f"could not remove clone cache {dest}: {ex}", file=sys.stderr)


def _cmd_ingest(args: argparse.Namespace) -> int:
    from codegraph.config import Settings
    from codegraph.ingestion.git import scrub

    try:
        asyncio.run(_ingest_async(args))
        return 0
    except Exception as exc:
        # Git errors echo the URL they were given, so a token would land in
        # stderr verbatim without scrubbing.
        token = Settings().git_token
        secret = token.get_secret_value() if token else None
        print(f"ingest failed: {scrub(str(exc), secret)}", file=sys.stderr)
        return 1


async def _ingest_async(args: argparse.Namespace) -> None:
    from codegraph.config import Settings
    from codegraph.ingestion.commits import collect_commits
    from codegraph.ingestion.git import (
        clone_or_fetch,
        local_path_for,
        repo_slug_from_url,
        sanitize_url,
    )
    from codegraph.ingestion.graph_builder import build_ingest_plan, run_plan
    from codegraph.ingestion.languages import support_for
    from codegraph.ingestion.walker import walk_repo
    from codegraph.models.ingestion import ExtractedFile
    from codegraph.repo.neo4j_adapter import Neo4jAdapter

    settings = Settings()
    adapter = Neo4jAdapter.from_settings(settings)
    try:
        await adapter.connect()
        await adapter.apply_migrations()

        slug = repo_slug_from_url(args.url)
        # Everything persisted or printed downstream uses the sanitized URL —
        # a credential must never reach Neo4j or the console.
        clean_url = sanitize_url(args.url)
        token = settings.git_token.get_secret_value() if settings.git_token else None
        dest = local_path_for(args.url, settings.repos_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        branch = clone_or_fetch(
            args.url,
            dest,
            args.branch,
            settings.ingest_depth,
            force=args.force,
            token=token,
            token_host=settings.git_token_host,
            token_username=settings.git_token_username,
        )

        print(f"cloned {slug} (branch {branch})", file=sys.stderr)
        entries = walk_repo(dest)
        files: list[ExtractedFile] = []
        for fe in entries:
            support = support_for(fe.language)
            if support is None:
                continue
            source = fe.abspath.read_bytes()
            try:
                files.append(support.parse(fe.path, source))
            except Exception as parse_exc:
                # Don't let one malformed file kill the whole ingest run
                print(f"WARNING: skipping {fe.path}: {parse_exc}", file=sys.stderr)

        print(f"  parsed {len(files)} of {len(entries)} files", file=sys.stderr)
        commits = collect_commits(dest)
        known_paths = {ef.path for ef in files}
        plan = build_ingest_plan(
            slug=slug,
            url=clean_url,
            branch=branch,
            files=files,
            commits=commits,
            known_paths=known_paths,
        )
        def _progress(done: int, total: int) -> None:
            pct = (done * 100) // total if total else 100
            print(f"  writing graph: {done}/{total} statements ({pct}%)", file=sys.stderr)

        summary = await run_plan(
            adapter,
            plan,
            batch_size=settings.ingest_batch_size,
            progress=_progress,
        )
        print(json.dumps({
            "graph_id": slug,
            "files": summary.files,
            "functions": summary.functions,
            "imports": summary.imports,
            "calls": summary.calls,
            "external_symbols": summary.external_symbols,
            "pruned": summary.pruned,
        }))
    finally:
        await adapter.close()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.version:
        print("codegraph 0.1.0")
        return 0
    if args.cmd is None:
        print("codegraph — run `codegraph --help` for usage", file=sys.stderr)
        return 0
    if args.cmd == "ingest":
        return _cmd_ingest(args)
    if args.cmd == "serve":
        return _cmd_serve()
    if args.cmd == "reset":
        return _cmd_reset(args)
    if args.cmd == "ls":
        return _cmd_ls()
    if args.cmd == "viz":
        return _cmd_viz(args)
    return 0
