"""run_plan batching — statements execute in batch_size-sized transactions,
without changing statement order, counting, or prune-count extraction."""

from __future__ import annotations

import math
from typing import Any

from codegraph.ingestion.graph_builder import run_plan


class _FakeBatchAdapter:
    """Records the batches it's called with; returns canned per-statement rows."""

    def __init__(self) -> None:
        self.batches: list[list[tuple[str, dict[str, Any]]]] = []

    async def _run_write_batch(
        self, statements: list[tuple[str, dict[str, Any]]]
    ) -> list[list[dict[str, Any]]]:
        self.batches.append(list(statements))
        results: list[list[dict[str, Any]]] = []
        for cypher, _params in statements:
            if "deleted = true" in cypher:
                results.append([{"c": 3}])
            else:
                results.append([])
        return results


def _fake_plan(n: int) -> list[tuple[str, dict[str, Any]]]:
    plan: list[tuple[str, dict[str, Any]]] = [
        (f"MERGE (f:File {{graph_id: $gid, path: $p{i}}})", {"gid": "o/n", f"p{i}": f"f{i}.py"})
        for i in range(n)
    ]
    # Prune statement placed mid-plan (not at the end) — proves batch position
    # doesn't matter for extracting the prune count.
    plan.insert(n // 2, ("MATCH (f:File) WHERE f.deleted = true RETURN count(f) AS c", {}))
    return plan


async def test_run_plan_batches_statements_in_order() -> None:
    plan = _fake_plan(9)
    fake = _FakeBatchAdapter()

    await run_plan(fake, plan, batch_size=3)

    assert len(fake.batches) == math.ceil(len(plan) / 3)
    # Concatenating the batches reproduces the original plan, in order.
    flattened = [stmt for batch in fake.batches for stmt in batch]
    assert flattened == plan


async def test_run_plan_extracts_prune_count_regardless_of_batch_position() -> None:
    plan = _fake_plan(9)
    fake = _FakeBatchAdapter()

    summary = await run_plan(fake, plan, batch_size=3)

    assert summary.pruned == 3


async def test_run_plan_counts_unaffected_by_batching() -> None:
    plan = _fake_plan(9)
    fake = _FakeBatchAdapter()

    summary = await run_plan(fake, plan, batch_size=3)

    assert summary.files == sum(1 for c, _ in plan if "MERGE (f:File" in c)


async def test_run_plan_default_batch_size_is_single_batch_for_small_plans() -> None:
    plan = _fake_plan(3)
    fake = _FakeBatchAdapter()

    await run_plan(fake, plan)  # no batch_size arg — must not error, default covers it

    assert len(fake.batches) == 1
