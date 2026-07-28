"""tree-sitter JS/TS parser — functions + imports + calls."""

from __future__ import annotations

from codegraph.ingestion.jsts_parser import parse_jsts

_TS_SOURCE = b'''
import { authenticate } from "./auth";

export function main(): void {
  if (authenticate("admin")) {
    console.log("ok");
  }
}

class UserService {
  get(uid: number): boolean { return true; }
}
'''


def test_extracts_function() -> None:
    ef = parse_jsts("svc.ts", _TS_SOURCE, "ts")
    names = {f.name for f in ef.functions}
    assert "main" in names


def test_extracts_class() -> None:
    ef = parse_jsts("svc.ts", _TS_SOURCE, "ts")
    assert any(f.kind == "class" and f.name == "UserService" for f in ef.functions)


def test_extracts_import() -> None:
    ef = parse_jsts("svc.ts", _TS_SOURCE, "ts")
    assert any(i.module == "./auth" and i.symbol == "authenticate" for i in ef.imports)


def test_extracts_call() -> None:
    ef = parse_jsts("svc.ts", _TS_SOURCE, "ts")
    callees = {c.callee_name for c in ef.calls}
    assert "authenticate" in callees
