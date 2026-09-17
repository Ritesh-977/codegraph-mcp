"""Pure file -> directory-cluster aggregation for the overview view.

Keeps the logic free of I/O so it is trivially unit-testable. Files whose
path is shallower than ``depth`` remain file nodes; deeper files are grouped
under their ``depth``-segment directory prefix as ``dir_cluster`` nodes.
Edges between clustered files aggregate into a single weighted edge between
the clusters; intra-cluster edges collapse to the cluster's self-loop and are
dropped.
"""

from __future__ import annotations

from collections import defaultdict

from codegraph.viz.models import GraphEdge, GraphNode


def cluster_key(path: str, depth: int) -> str | None:
    """Return the ``depth``-segment prefix, or None if the path is not deeper.

    ``cluster_key("a.py", 1)`` -> None (root files stay visible files);
    ``cluster_key("src/a.py", 1)`` -> "src".
    """
    parts = path.split("/")
    if len(parts) <= depth:
        return None
    return "/".join(parts[:depth])


def build_cluster_graph(
    nodes: list[GraphNode], edges: list[GraphEdge], depth: int
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Cluster ``nodes``/``edges`` at ``depth``; return sorted cluster nodes+edges."""
    path_by_id = {n.id: n.path or n.label for n in nodes}

    clusters: dict[str, int] = defaultdict(int)
    shallow: list[GraphNode] = []
    for n in nodes:
        key = cluster_key(n.path or n.label, depth)
        if key is None:
            shallow.append(n)
        else:
            clusters[key] += 1

    def resolve(nid: str) -> str:
        key = cluster_key(path_by_id[nid], depth)
        return f"dir:{key}" if key is not None else nid

    out_nodes: list[GraphNode] = shallow[:]
    out_nodes.extend(
        GraphNode(
            id=f"dir:{key}",
            kind="dir_cluster",
            label=key.rsplit("/", 1)[-1],
            path=key,
            file_count=count,
        )
        for key, count in sorted(clusters.items())
    )
    out_nodes.sort(key=lambda n: n.id)  # deterministic payloads for the UI + tests

    agg: dict[tuple[str, str], int] = defaultdict(int)
    for e in edges:
        s, t = resolve(e.source), resolve(e.target)
        if s == t:
            continue
        agg[(s, t)] += 1
    out_edges = [
        GraphEdge(source=s, target=t, type="IMPORTS", weight=w)
        for (s, t), w in sorted(agg.items())
    ]
    return out_nodes, out_edges
