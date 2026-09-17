"""Python AST parser → ExtractedFile. No I/O except reading bytes (caller does)."""

from __future__ import annotations

import ast
from dataclasses import replace

from codegraph.models.ingestion import (
    ExtractedCall,
    ExtractedFile,
    ExtractedFunction,
    ExtractedImport,
)


def parse_python(path: str, source: bytes) -> ExtractedFile:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        # Malformed source — return an empty ExtractedFile so the ingest
        # pipeline can skip this file without crashing the whole batch.
        return ExtractedFile(path=path, language="py")
    functions: list[ExtractedFunction] = []
    imports: list[ExtractedImport] = []
    calls: list[ExtractedCall] = []

    # Receiver variable -> class name, from `x = ClassName()` bindings and
    # `def f(x: ClassName)` annotations. Deliberately file-scoped and flat: this
    # is disambiguation for the common cases, not type inference.
    receiver_types: dict[str, str] = {}

    class _Visitor(ast.NodeVisitor):
        def __init__(self, file_path: str) -> None:
            self._stack: list[str] = []
            self._classes: list[str] = []
            self._file_path = file_path

        def _qname(self, name: str) -> str:
            """Build a file-scoped qualified name: `path::Class.method` or `path::func`."""
            dotted = ".".join([*self._stack, name]) if self._stack else name
            return f"{self._file_path}::{dotted}"

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            q = self._qname(node.name)
            functions.append(ExtractedFunction(
                name=node.name, qualified_name=q, kind="class",
                start_line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
            ))
            self._stack.append(node.name)
            self._classes.append(node.name)
            self.generic_visit(node)
            self._classes.pop()
            self._stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._handle_func(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._handle_func(node)

        def _handle_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            kind = "method" if self._stack else "function"
            q = self._qname(node.name)
            functions.append(ExtractedFunction(
                name=node.name, qualified_name=q, kind=kind,
                start_line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
            ))
            # `def f(x: Foo)` — the annotation tells us x's type.
            for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                ann = _annotation_name(arg.annotation)
                if ann:
                    receiver_types.setdefault(arg.arg, ann)
            self._stack.append(node.name)
            self.generic_visit(node)
            self._stack.pop()

        def visit_Assign(self, node: ast.Assign) -> None:
            # `x = ClassName()` — bind x to that class for later `x.method()`.
            if isinstance(node.value, ast.Call):
                cls = _callee_name(node.value)
                if cls[:1].isupper():
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            receiver_types.setdefault(tgt.id, cls)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            ann = _annotation_name(node.annotation)
            if ann and isinstance(node.target, ast.Name):
                receiver_types.setdefault(node.target.id, ann)
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                imports.append(ExtractedImport(module=alias.name, symbol="", resolved_path=None))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            # Preserve relative-import level so the resolver's relative branch fires.
            # `from .sub import x` → module=".sub"; `from . import x` → module="."
            mod = ("." * node.level) + (node.module or "")
            for alias in node.names:
                imports.append(ExtractedImport(module=mod, symbol=alias.name, resolved_path=None))

        def visit_Call(self, node: ast.Call) -> None:
            dotted = ".".join(self._stack) if self._stack else "<module>"
            caller = f"{self._file_path}::{dotted}"
            callee = _callee_name(node)
            if callee:
                calls.append(ExtractedCall(
                    caller_qname=caller,
                    callee_name=callee,
                    receiver=_receiver_name(node),
                    caller_class=self._classes[-1] if self._classes else None,
                ))
            self.generic_visit(node)

    _Visitor(path).visit(tree)
    # Rewrite each call's receiver to the class it was bound to, where known,
    # so the resolver gets a class name rather than a variable name.
    calls = [
        replace(c, receiver=receiver_types.get(c.receiver, c.receiver))
        if c.receiver and c.receiver != "self"
        else c
        for c in calls
    ]
    return ExtractedFile(path=path, language="py", functions=functions, imports=imports, calls=calls)


def _receiver_name(node: ast.Call) -> str | None:
    """`self.m()` -> "self"; `user.save()` -> "user"; `helper()` -> None."""
    f = node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f.value.id
    return None


def _annotation_name(ann: ast.expr | None) -> str | None:
    """Class name from a type annotation, ignoring subscripts/optionals."""
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    return None


def _callee_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""
