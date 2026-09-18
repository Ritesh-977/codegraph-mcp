"""Pure graph analysis: layering, cycles, hubs, orphans."""

from __future__ import annotations

from codegraph.viz.analysis import analyze


def test_chain_layers_from_entry_downward() -> None:
    m = analyze(["a", "b", "c"], [("a", "b"), ("b", "c")])
    assert m.layer == {"a": 0, "b": 1, "c": 2}
    assert m.fan_in == {"b": 1, "c": 1}
    assert m.fan_out == {"a": 1, "b": 1}
    assert m.entry_points == ["a"]
    assert m.cycles == []
    assert m.orphans == []


def test_longest_path_wins_so_layers_never_cross() -> None:
    # a -> b -> c and a -> c: c must sit below b, not beside it.
    m = analyze(["a", "b", "c"], [("a", "b"), ("b", "c"), ("a", "c")])
    assert m.layer["c"] == 2


def test_cycle_is_reported_and_does_not_break_layering() -> None:
    m = analyze(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "b")])
    assert m.cycles == [["b", "c"]]
    # members of a cycle share a layer (the cycle collapses to one row)
    assert m.layer["b"] == m.layer["c"] == 1


def test_self_loop_is_not_a_cycle_finding() -> None:
    m = analyze(["a"], [("a", "a")])
    assert m.cycles == []


def test_orphans_and_entry_points_are_distinct() -> None:
    m = analyze(["a", "b", "lonely"], [("a", "b")])
    assert m.orphans == ["lonely"]
    assert m.entry_points == ["a"]  # an orphan is not an entry point


def test_hubs_rank_by_dependents_then_name() -> None:
    m = analyze(
        ["hub", "x", "y", "z", "small"],
        [("x", "hub"), ("y", "hub"), ("z", "hub"), ("x", "small")],
    )
    assert m.hubs[0] == ("hub", 3)
    assert ("small", 1) in m.hubs


def test_deterministic_ordering() -> None:
    m = analyze(["b", "a"], [])
    assert m.orphans == ["a", "b"]
