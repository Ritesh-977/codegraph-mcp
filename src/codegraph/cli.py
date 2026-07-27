"""CLI dispatch — subcommand routing, no business logic."""

from __future__ import annotations

import argparse
import sys


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

    sub.add_parser("ls", help="List ingested repos in Neo4j")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.version:
        print("codegraph 0.1.0")
        return 0
    if args.cmd is None:
        print("codegraph — run `codegraph --help` for usage", file=sys.stderr)
        return 0
    if args.cmd == "ingest":
        # Implemented in Day 3 (after parsers + graph_builder land).
        print(f"ingest not yet implemented (url={args.url})", file=sys.stderr)
        return 2
    if args.cmd == "serve":
        # Implemented in Day 4.
        print("serve not yet implemented", file=sys.stderr)
        return 2
    if args.cmd == "reset":
        # Implemented in Day 3.
        print("reset not yet implemented", file=sys.stderr)
        return 2
    if args.cmd == "ls":
        # Implemented in Day 4.
        print("ls not yet implemented", file=sys.stderr)
        return 2
    return 0
