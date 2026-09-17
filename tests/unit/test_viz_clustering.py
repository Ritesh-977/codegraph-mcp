"""Pure directory-clustering for the overview view."""

from __future__ import annotations

from codegraph.viz.clustering import build_cluster_graph, cluster_key
from codegraph.viz.models import GraphEdge, GraphNode


def _node(nid: str, path: str) -> GraphNode:
    return GraphNode(id=nid, kind="file", label=path.rsplit("/", 1)[-1], path=path)


def test_cluster_key_depth1() -> None:
    assert cluster_key("a.py", 1) is None            # root file stays file node
    assert cluster_key("src/a.py", 1) == "src"
    assert cluster_key("src/deep/a.py", 1) == "src"
    assert cluster_key("src/deep/a.py", 2) == "src/deep"


def test_build_cluster_graph_groups_and_aggregates() -> None:
    nodes = [
        _node("f:a.py", "a.py"),
        _node("f:src/a1.py", "src/a1.py"),
        _node("f:src/a2.py", "src/a2.py"),
        _node("f:lib/u.py", "lib/u.py"),
    ]
    edges = [
        GraphEdge(source="f:a.py", target="f:src/a1.py", type="IMPORTS"),
        GraphEdge(source="f:src/a1.py", target="f:src/a2.py", type="IMPORTS"),
        GraphEdge(source="f:src/a1.py", target="f:a.py", type="IMPORTS"),
        GraphEdge(source="f:src/a2.py", target="f:lib/u.py", type="IMPORTS"),
    ]
    cn, ce = build_cluster_graph(nodes, edges, depth=1)
    kinds = {n.kind for n in cn}
    assert "dir_cluster" in kinds and "file" in kinds
    # a.py stays a file node
    assert any(n.id == "f:a.py" for n in cn)
    # dirs become clusters with counts
    src = next(n for n in cn if n.id == "dir:src")
    lib = next(n for n in cn if n.id == "dir:lib")
    assert src.file_count == 2
    assert lib.file_count == 1
    # aggregated edge weights
    agg = {(e.source, e.target): e.weight for e in ce}
    assert agg[("f:a.py", "dir:src")] == 1
    # two distinct src files import/export: src/a1 -> a2 is an internal edge,
    # dropped as a self-loop; src->a.py counts once
    assert agg[("dir:src", "f:a.py")] == 1
    assert agg[("dir:src", "dir:lib")] == 1
    # deterministic ordering
    assert [n.id for n in cn] == sorted(n.id for n in cn)
