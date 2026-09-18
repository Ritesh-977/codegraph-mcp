"""Lucene query sanitisation for ranked search.

The full-text parser rejects inputs an LLM will plausibly send (a bare `~`,
unbalanced quotes, `foo(`). A search tool that raises on odd input is worse
than one that degrades, so the query is escaped before it reaches Lucene.
"""

from __future__ import annotations

import pytest

from codegraph.repo.neo4j_adapter import _fulltext_query


@pytest.mark.parametrize(
    "raw",
    ['foo(', 'a~', 'unbalanced "quote', "sla/sh", "plus+minus-", "brack[et]", "car^et"],
)
def test_hostile_queries_are_escaped_not_raised(raw: str) -> None:
    out = _fulltext_query(raw)
    assert out, "must always produce a usable query string"


def test_terms_become_prefix_queries() -> None:
    """Users expect partial-name matching, as the old CONTAINS gave them."""
    assert _fulltext_query("search bar") == "search* bar*"


def test_empty_query_is_safe() -> None:
    assert _fulltext_query("   ") == "*"
