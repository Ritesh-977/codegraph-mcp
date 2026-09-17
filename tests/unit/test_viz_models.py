"""Wire-format model validation for codegraph-viz."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from codegraph.models.common import MAX_TRAVERSAL_HOPS
from codegraph.viz.models import (
    GraphPayload,
    ImpactRequest,
    SubgraphRequest,
)


def test_subgraph_requires_valid_direction() -> None:
    with pytest.raises(ValidationError):
        SubgraphRequest(graph_id="o/n", seed_path="a.py", direction="sideways")


def test_subgraph_depth_bounds() -> None:
    with pytest.raises(ValidationError):
        SubgraphRequest(graph_id="o/n", seed_path="a.py", depth=0)
    with pytest.raises(ValidationError):
        SubgraphRequest(graph_id="o/n", seed_path="a.py", depth=MAX_TRAVERSAL_HOPS + 1)
    ok = SubgraphRequest(graph_id="o/n", seed_path="a.py", depth=2)
    assert ok.direction == "both"
    assert ok.include_symbols is True


def test_impact_max_hops_bounds() -> None:
    with pytest.raises(ValidationError):
        ImpactRequest(graph_id="o/n", seed_path="a.py", max_hops=0)
    ok = ImpactRequest(graph_id="o/n", seed_path="a.py", max_hops=1)
    assert ok.max_hops == 1


def test_graph_payload_roundtrip() -> None:
    payload = GraphPayload.model_validate({
        "graph_id": "o/n",
        "view": "full",
        "nodes": [{"id": "file:a.py", "kind": "file", "label": "a.py", "path": "a.py", "language": "python"}],
        "edges": [{"source": "file:a.py", "target": "sym:os", "type": "IMPORTS"}],
        "stats": {"file_count": 1, "edge_count": 1, "truncated": False, "view": "full"},
    })
    assert payload.nodes[0].path == "a.py"
    assert payload.edges[0].type == "IMPORTS"
