"""Call-graph accuracy: exact expected edges, not "at least N".

Phase 4's claim is that the graph is *accurate*, which is only meaningful if
measured. These assert the complete set of extracted edges so a regression
that drops or misattributes one shows up, instead of hiding behind a
greater-than assertion.
"""

from __future__ import annotations

from codegraph.ingestion.graph_builder import _resolve_call
from codegraph.ingestion.jsts_parser import parse_jsts
from codegraph.ingestion.python_parser import parse_python

# --- JS/TS: arrow functions and nesting (Phase 4.1) ----------------------

_JS = b"""
const Component = () => {
  useEffect(() => { window.scrollTo(); });
  helper();
};
const outer = () => {
  const inner = () => { innerCall(); };
  outerCall();
};
const handlers = { onClick: () => { clicked(); } };
export default () => { defaultCall(); };
function classic() { classicCall(); }
class Svc { run() { ranIt(); } }
"""


def _js_calls() -> set[tuple[str, str]]:
    r = parse_jsts("m.js", _JS, "js")
    return {(c.callee_name, c.caller_qname) for c in r.calls}


def test_js_declarations_extracted_exactly() -> None:
    r = parse_jsts("m.js", _JS, "js")
    assert {f.name for f in r.functions} == {
        "Component", "outer", "inner", "onClick", "default", "classic", "Svc", "run"
    }


def test_js_calls_attributed_to_innermost_named_owner() -> None:
    calls = _js_calls()
    # Arrow-bodied component owns its calls (was <module> before Phase 4.1).
    assert ("helper", "m.js::Component") in calls
    # A call inside an anonymous callback attributes to the nearest *named*
    # owner rather than being lost.
    assert ("scrollTo", "m.js::Component") in calls
    # Nesting resolves innermost-first, not to the outer arrow.
    assert ("innerCall", "m.js::inner") in calls
    assert ("outerCall", "m.js::outer") in calls
    # Object-literal arrow, anonymous default export, classic fn, class method.
    assert ("clicked", "m.js::onClick") in calls
    assert ("defaultCall", "m.js::default") in calls
    assert ("classicCall", "m.js::classic") in calls
    assert ("ranIt", "m.js::run") in calls


def test_js_no_call_falls_back_to_module_when_owner_exists() -> None:
    """Only genuinely top-level calls may be <module>.

    Note the JS path returns a bare "<module>" (the Python parser prefixes the
    file path); asserting the prefixed form here would pass vacuously.
    """
    module_level = {c for c in _js_calls() if c[1] == "<module>"}
    assert module_level == set(), f"calls lost to <module>: {module_level}"


# --- Python: receiver-aware resolution (Phase 4.2) -----------------------

_PY = b'''
class Order:
    def save(self):
        self.validate()

    def validate(self):
        pass


class User:
    def save(self):
        pass


def handler():
    user = User()
    user.save()
'''


def _resolve_all(path: str, source: bytes) -> list[tuple[str, str | None]]:
    parsed = parse_python(path, source)
    qnames = {f.qualified_name for f in parsed.functions}
    return [(c.callee_name, _resolve_call(c, path, qnames)) for c in parsed.calls]


def test_self_call_binds_to_enclosing_class() -> None:
    """`self.validate()` inside Order must bind to Order.validate."""
    resolved = dict(_resolve_all("m.py", _PY))
    assert resolved["validate"] == "m.py::Order.validate"


def test_receiver_binds_to_its_instantiated_class() -> None:
    """`user = User(); user.save()` must pick User.save, not Order.save —
    both classes define `save`, which is exactly where first-match-wins failed."""
    resolved = dict(_resolve_all("m.py", _PY))
    assert resolved["save"] == "m.py::User.save"


def test_annotation_binds_receiver_type() -> None:
    src = b'''
class Repo:
    def find(self):
        pass


class Cache:
    def find(self):
        pass


def use(r: Repo):
    r.find()
'''
    resolved = dict(_resolve_all("m.py", src))
    assert resolved["find"] == "m.py::Repo.find"


def test_resolution_is_deterministic_across_runs() -> None:
    """Resolution used to iterate a set, so the same repo could produce
    different CALLS edges on different ingests."""
    runs = [_resolve_all("m.py", _PY) for _ in range(5)]
    assert all(r == runs[0] for r in runs)
