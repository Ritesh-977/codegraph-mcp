"""Pure structural analysis of the import graph.

This is the part that turns a picture of a graph into an answer about a
codebase: which files are the spine, which are unreachable, where the cycles
are, and how deep the dependency stack goes. Everything here is pure —
node ids and edges in, metrics out — so it is cheap to test and reusable by
both the layered layout and the findings panel.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GraphMetrics:
    """Structural facts about one import graph.

    ``layer`` is the longest-path depth from an entry point, computed on the
    graph's condensation so that cycles collapse to a single row instead of
    making depth undefined.
    """

    fan_in: dict[str, int] = field(default_factory=dict)
    fan_out: dict[str, int] = field(default_factory=dict)
    layer: dict[str, int] = field(default_factory=dict)
    cycles: list[list[str]] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    hubs: list[tuple[str, int]] = field(default_factory=list)

    @property
    def max_layer(self) -> int:
        return max(self.layer.values(), default=0)


def _sccs(nodes: list[str], adj: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's SCC, iterative — a deep import chain must not blow the stack."""
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0

    for root in nodes:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            v, pi = work[-1]
            if pi == 0:
                index[v] = lowlink[v] = counter
                counter += 1
                stack.append(v)
                on_stack[v] = True
            recurse = False
            succs = adj.get(v, [])
            for i in range(pi, len(succs)):
                w = succs[i]
                if w not in index:
                    work[-1] = (v, i + 1)
                    work.append((w, 0))
                    recurse = True
                    break
                if on_stack.get(w):
                    lowlink[v] = min(lowlink[v], index[w])
            if recurse:
                continue
            if lowlink[v] == index[v]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    comp.append(w)
                    if w == v:
                        break
                out.append(comp)
            work.pop()
            if work:
                u = work[-1][0]
                lowlink[u] = min(lowlink[u], lowlink[v])
    return out


def analyze(node_ids: Iterable[str], edges: Iterable[tuple[str, str]]) -> GraphMetrics:
    """Compute fan-in/out, layering, cycles, entry points, orphans and hubs."""
    nodes = sorted(set(node_ids))
    known = set(nodes)
    pairs = [(s, t) for s, t in edges if s in known and t in known]

    fan_in: dict[str, int] = defaultdict(int)
    fan_out: dict[str, int] = defaultdict(int)
    adj: dict[str, list[str]] = defaultdict(list)
    for s, t in pairs:
        fan_out[s] += 1
        fan_in[t] += 1
        if t not in adj[s]:
            adj[s].append(t)

    comps = _sccs(nodes, adj)
    comp_of: dict[str, int] = {}
    for i, comp in enumerate(comps):
        for n in comp:
            comp_of[n] = i

    # Condensation: one node per SCC, so longest-path layering is well defined.
    cadj: dict[int, set[int]] = defaultdict(set)
    cin: dict[int, int] = defaultdict(int)
    for s, t in pairs:
        cs, ct = comp_of[s], comp_of[t]
        if cs != ct and ct not in cadj[cs]:
            cadj[cs].add(ct)
            cin[ct] += 1

    # Kahn's algorithm, taking the longest (not shortest) path to each node so
    # a file always renders below everything that imports it.
    clayer: dict[int, int] = {i: 0 for i in range(len(comps))}
    indeg = {i: cin.get(i, 0) for i in range(len(comps))}
    queue = [i for i in range(len(comps)) if indeg[i] == 0]
    while queue:
        c = queue.pop()
        for nxt in cadj.get(c, ()):
            clayer[nxt] = max(clayer[nxt], clayer[c] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)

    layer = {n: clayer[comp_of[n]] for n in nodes}
    # A self-loop is a one-file SCC; only a genuine multi-file tangle counts.
    cycles = sorted((sorted(c) for c in comps if len(c) > 1), key=lambda c: (-len(c), c))
    connected = {n for n in nodes if fan_in.get(n) or fan_out.get(n)}
    entry_points = sorted(n for n in connected if not fan_in.get(n))
    orphans = sorted(n for n in nodes if n not in connected)
    hubs = sorted(fan_in.items(), key=lambda kv: (-kv[1], kv[0]))

    return GraphMetrics(
        fan_in=dict(fan_in),
        fan_out=dict(fan_out),
        layer=layer,
        cycles=cycles,
        entry_points=entry_points,
        orphans=orphans,
        hubs=hubs,
    )
