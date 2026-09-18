"""Unit tests for the max_hops literal-embedding guard.

Neo4j can't parameterize a variable-length relationship pattern's bound
(`[:IMPORTS*1..$max_hops]` is a syntax error), so `find_file_dependencies`
range-checks `max_hops` in Python before splicing it into Cypher text as a
literal. This is the one piece of that change that's pure Python and doesn't
need a live Neo4j (see the integration tests for the Cypher itself).
"""

from __future__ import annotations

import pytest

from codegraph.models.common import MAX_TRAVERSAL_HOPS
from codegraph.repo.neo4j_adapter import _validated_hop_bound


def test_validated_hop_bound_accepts_range_endpoints() -> None:
    assert _validated_hop_bound(0) == 0
    assert _validated_hop_bound(MAX_TRAVERSAL_HOPS) == MAX_TRAVERSAL_HOPS


def test_validated_hop_bound_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="max_hops"):
        _validated_hop_bound(MAX_TRAVERSAL_HOPS + 1)
    with pytest.raises(ValueError, match="max_hops"):
        _validated_hop_bound(-1)


def test_validated_hop_bound_rejects_bool() -> None:
    # bool is a subclass of int in Python — must not silently pass as 0/1.
    with pytest.raises(ValueError, match="max_hops"):
        _validated_hop_bound(True)  # type: ignore[arg-type]
