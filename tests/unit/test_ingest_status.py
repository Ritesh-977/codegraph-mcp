"""Ingest status marker and progress reporting (Phase 6.1)."""

from __future__ import annotations

from codegraph.ingestion.graph_builder import build_ingest_plan, run_plan
from codegraph.models.ingestion import ExtractedFile


def _plan():
    return build_ingest_plan(
        slug="github.com/o/n", url="https://github.com/o/n", branch="main",
        files=[ExtractedFile(path="a.py", language="py")], commits={},
        known_paths={"a.py"},
    )


def test_ingested_at_is_stamped_last_not_first() -> None:
    """It used to be set in statement 1, so an ingest that died at 80% still
    left a Repository claiming a fresh timestamp — list_repos then reported a
    half-written graph as freshly ingested."""
    plan = _plan()
    stamped = [i for i, (cy, _) in enumerate(plan) if "ingested_at" in cy]
    assert stamped == [len(plan) - 1], "ingested_at must only land in the final statement"


def test_first_statement_marks_running() -> None:
    cy, _ = _plan()[0]
    assert "ingest_status = 'running'" in cy


def test_final_statement_marks_complete() -> None:
    cy, _ = _plan()[-1]
    assert "ingest_status = 'complete'" in cy
    assert "ingested_at" in cy


class _FakeAdapter:
    async def _run_write_batch(self, statements):
        return [[] for _ in statements]


async def test_progress_callback_reports_each_batch() -> None:
    plan = _plan() * 3  # enough statements to span several batches
    seen: list[tuple[int, int]] = []
    await run_plan(_FakeAdapter(), plan, batch_size=2, progress=lambda d, t: seen.append((d, t)))

    assert seen, "progress must be reported"
    assert seen[-1] == (len(plan), len(plan)), "final call must report completion"
    assert all(d <= t for d, t in seen)
    assert [d for d, _ in seen] == sorted(d for d, _ in seen), "must advance monotonically"


async def test_progress_is_optional() -> None:
    """Existing callers pass no progress callback."""
    await run_plan(_FakeAdapter(), _plan(), batch_size=2)
