"""Stage 2 indexing acceptance tests.

These tests exercise Engine/queue batch indexing against the real Chroma
persistent store with deterministic fake embeddings; no models are downloaded.
Queue time is controlled through a SimpleNamespace clock patched onto the
task_queue module instead of using real sleeps.

Chroma is the only durable indexing record: no per-batch metadata pickle is
written anymore. Assertions therefore use the cheap public stats and the real
stored Chroma rows, with old cache fixtures only appearing where a legacy
"analyzed" pickle mark must be proven harmless.
"""

import math
from pathlib import Path
from queue import PriorityQueue
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from seagoat.cache import Cache
from seagoat.engine import Engine
from seagoat.queue import task_queue as task_queue_module
from seagoat.queue.base_queue import HIGH_PRIORITY
from seagoat.queue.indexing_scheduler import make_batches
from seagoat.queue.task_queue import TaskQueue
from seagoat.sources import chroma
from seagoat.sources.chroma import EmbeddingError
from tests.fixtures.scheduling import attach_lane, drive, manual_scheduler
from tests.test_chroma_batches import (
    _chunk,
    _DeterministicEmbeddingFunction,
    _open_collection,
    _SwitchableEmbeddingFunction,
)


class _PoisonEmbeddingFunction(_DeterministicEmbeddingFunction):
    """Deterministic fake embeddings that fail on the POISON marker text."""

    def __call__(self, input):
        texts = list(input)
        if any("POISON" in text for text in texts):
            raise RuntimeError("poison text encountered")
        return super().__call__(texts)


def _make_engine(repo_path, embedding_function):
    with patch.object(
        chroma, "_get_embedding_function", return_value=embedding_function
    ):
        return Engine(repo_path)


def _make_queue(engine, clock=None):
    queue = TaskQueue.__new__(TaskQueue)
    queue.kwargs = {}
    queue._task_queue = PriorityQueue()
    context = {
        "seagoat_engine": engine,
        "last_maintenance": None,
        "last_repo_state_hash": None,
    }
    queue._ensure_recovery_state(context)
    scheduler = manual_scheduler(clock=(lambda: clock[0]) if clock else None)
    attach_lane(queue, context, scheduler)
    return queue, context


def _drive(queue, context, handled=None):
    return drive(queue, context, handled)


def _seed_legacy_marks(engine, chunk_ids):
    """Construct an OLD cache fixture: analyzed marks without stored vectors."""
    legacy_cache = Cache("cache", Path(engine.path), dict(engine.cache.data))
    legacy_cache.data.update(
        {
            "chunks_already_analyzed": set(chunk_ids),
            "chunks_not_yet_analyzed": set(),
        }
    )
    legacy_cache.persist()


def _clock_patch(clock):
    # Scope the clock to this module rather than patching global time.
    # Maintenance and recovery both use its monotonic clock.
    return patch.object(
        task_queue_module,
        "time",
        SimpleNamespace(time=lambda: clock[0], monotonic=lambda: clock[0]),
    )


def test_engine_indexes_all_chunks_without_persisting_per_batch(
    repo, create_config_file
):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    engine = _make_engine(repo.working_dir, _DeterministicEmbeddingFunction())
    chunks = engine.plan_indexing()
    current_ids = {chunk.chunk_id for chunk in chunks}
    assert current_ids

    persist_calls = []
    original_persist = engine.cache.persist

    def recording_persist():
        persist_calls.append(1)
        original_persist()

    engine.cache.persist = recording_persist

    source = engine._fetchers["sync"][0]
    real_cache_batch = source["cache_batch"]
    batch_sizes = []
    persist_at_batch = []

    def recording_cache_batch(batch):
        batch_ids = {chunk.chunk_id for chunk in batch}
        # Nothing for this batch may be visible in Chroma before its own upsert.
        stored_ids = set(_open_collection(repo.working_dir).get(include=[])["ids"])
        assert not batch_ids & stored_ids
        batch_sizes.append(len(batch_ids))
        persist_at_batch.append(len(persist_calls))
        real_cache_batch(batch)

    source["cache_batch"] = recording_cache_batch

    remaining = engine.analyze_codebase(minimum_chunks_to_analyze=len(chunks))
    assert remaining == []
    stats = engine.get_indexing_stats()
    assert stats["analyzed"] == len(current_ids)
    assert stats["pending"] == 0
    assert stats["total"] == len(current_ids)

    stored = _open_collection(repo.working_dir).get(ids=sorted(current_ids), include=[])
    assert set(stored["ids"]) == current_ids

    expected_batches = math.ceil(len(chunks) / 4)
    assert len(batch_sizes) == expected_batches
    full_batches, remainder = divmod(len(chunks), 4)
    expected_sizes = [4] * full_batches + ([remainder] if remainder else [])
    assert batch_sizes == expected_sizes

    # Batch completion never pickles: the only metadata persistence is the
    # plan-time snapshot, and no persist call happened while batches ran.
    assert len(persist_calls) == 1  # the plan inside analyze_codebase
    assert set(persist_at_batch) == {1}


@pytest.mark.parametrize("limit", [1, 2, 4])
def test_analyze_codebase_explicit_limits_still_honored(
    repo, create_config_file, limit
):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    engine = _make_engine(repo.working_dir, _DeterministicEmbeddingFunction())
    chunks = engine.plan_indexing()
    assert len(chunks) >= 4

    remaining = engine.analyze_codebase(minimum_chunks_to_analyze=limit)

    assert len(remaining) == len(chunks) - limit
    stats = engine.get_indexing_stats()
    assert stats["analyzed"] == limit
    assert stats["pending"] == len(chunks) - limit
    assert stats["total"] == len(chunks)
    stored = _open_collection(repo.working_dir).get(include=[])
    assert set(stored["ids"]) == {chunk.chunk_id for chunk in chunks[:limit]}


def test_legacy_repair_requeues_absent_rows(repo, create_config_file):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    embedding_function = _DeterministicEmbeddingFunction()
    first = _make_engine(repo.working_dir, embedding_function)
    chunks = first.plan_indexing()
    current_ids = {chunk.chunk_id for chunk in chunks}
    assert current_ids

    # Old behavior marked chunks analyzed without ever storing vectors.
    _seed_legacy_marks(first, current_ids)
    stored = _open_collection(repo.working_dir).get(ids=sorted(current_ids), include=[])
    assert stored["ids"] == []

    fresh = _make_engine(repo.working_dir, embedding_function)
    # Legacy pickle keys are stripped on load and never trusted again.
    assert "chunks_already_analyzed" not in fresh.cache.data
    assert "chunks_not_yet_analyzed" not in fresh.cache.data
    stats = fresh.get_indexing_stats()
    assert stats["analyzed"] == 0
    assert stats["pending"] == 0

    # Marked-but-missing rows make automatic repair: the whole snapshot is
    # pending again because Chroma holds none of the current chunks.
    pending = fresh.plan_indexing()
    assert {chunk.chunk_id for chunk in pending} == current_ids
    stats = fresh.get_indexing_stats()
    assert stats["pending"] == len(current_ids)
    assert stats["analyzed"] == 0

    fresh.analyze_codebase(minimum_chunks_to_analyze=len(pending))
    stats = fresh.get_indexing_stats()
    assert stats["analyzed"] == len(current_ids)
    assert stats["pending"] == 0

    stored = _open_collection(repo.working_dir).get(ids=sorted(current_ids), include=[])
    assert set(stored["ids"]) == current_ids


def test_failed_reconciliation_read_recovers_without_commit(repo, create_config_file):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    embedding_function = _DeterministicEmbeddingFunction()
    first = _make_engine(repo.working_dir, embedding_function)
    chunks = first.plan_indexing()
    current_ids = {chunk.chunk_id for chunk in chunks}
    _seed_legacy_marks(first, current_ids)

    fresh = _make_engine(repo.working_dir, embedding_function)
    assert "chunks_already_analyzed" not in fresh.cache.data
    source = fresh._fetchers["sync"][0]
    real_indexed_ids = source["indexed_ids"]
    calls = {"n": 0}

    def flaky_indexed_ids(ids):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("chroma read outage")
        return real_indexed_ids(ids)

    source["indexed_ids"] = flaky_indexed_ids

    with pytest.raises(RuntimeError, match="chroma read outage"):
        fresh.plan_indexing()

    assert calls["n"] == 1
    # The failed reconciliation published nothing: no plan state, no rows.
    stats = fresh.get_indexing_stats()
    assert stats["analyzed"] == 0
    assert stats["pending"] == 0
    assert _open_collection(repo.working_dir).get(include=[])["ids"] == []

    pending = fresh.plan_indexing()
    assert calls["n"] == 2
    assert {chunk.chunk_id for chunk in pending} == current_ids
    stats = fresh.get_indexing_stats()
    assert stats["pending"] == len(current_ids)
    assert stats["analyzed"] == 0

    fresh.analyze_codebase(minimum_chunks_to_analyze=len(pending))
    stats = fresh.get_indexing_stats()
    assert stats["analyzed"] == len(current_ids)
    assert stats["pending"] == 0
    stored = _open_collection(repo.working_dir).get(ids=sorted(current_ids), include=[])
    assert set(stored["ids"]) == current_ids


def test_embed_failure_marks_nothing_and_is_retryable(repo, create_config_file):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    embedding_function = _SwitchableEmbeddingFunction()
    embedding_function.fail = True
    engine = _make_engine(repo.working_dir, embedding_function)
    chunks = engine.plan_indexing()
    stats = engine.get_indexing_stats()
    total = stats["total"]
    assert total >= 4
    batch = chunks[:4]
    batch_ids = {chunk.chunk_id for chunk in batch}
    assert len(batch_ids) == 4

    with pytest.raises(EmbeddingError):
        engine.process_batch(batch)

    # Nothing was committed: stats unchanged and no rows reached Chroma.
    stats = engine.get_indexing_stats()
    assert stats["analyzed"] == 0
    assert stats["pending"] == total
    stored = _open_collection(repo.working_dir).get(ids=sorted(batch_ids), include=[])
    assert stored["ids"] == []

    # After the model recovers the same batch succeeds and reaches storage.
    embedding_function.fail = False
    engine.process_batch(batch)
    stats = engine.get_indexing_stats()
    assert stats["analyzed"] == len(batch_ids)
    assert stats["pending"] == total - len(batch_ids)
    stored = _open_collection(repo.working_dir).get(ids=sorted(batch_ids), include=[])
    assert set(stored["ids"]) == batch_ids


def test_batch_succeeds_even_if_cache_persist_fails(repo, create_config_file):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    engine = _make_engine(repo.working_dir, _DeterministicEmbeddingFunction())
    chunks = engine.plan_indexing()
    total = engine.get_indexing_stats()["total"]
    batch = chunks[:4]
    batch_ids = {chunk.chunk_id for chunk in batch}

    def broken_persist():
        raise OSError("disk full")

    engine.cache.persist = broken_persist

    # Batch completion no longer pickles, so a broken cache.persist cannot
    # fail the batch: the rows still reach Chroma and stats advance.
    engine.process_batch(batch)
    stats = engine.get_indexing_stats()
    assert stats["analyzed"] == len(batch_ids)
    assert stats["pending"] == total - len(batch_ids)

    stored = _open_collection(repo.working_dir).get(ids=sorted(batch_ids), include=[])
    assert set(stored["ids"]) == batch_ids
    assert len(stored["ids"]) == len(batch_ids)  # upsert replaced, no duplicates


def test_plan_time_metadata_persist_failure_is_retryable(repo, create_config_file):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    engine = _make_engine(repo.working_dir, _DeterministicEmbeddingFunction())
    calls = {"n": 0}
    original_persist = engine.cache.persist

    def flaky_persist():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        original_persist()

    engine.cache.persist = flaky_persist

    with pytest.raises(OSError, match="disk full"):
        engine.plan_indexing()

    # A failed metadata persistence publishes no plan; stats stay empty and
    # no rows were written.
    assert calls["n"] == 1
    stats = engine.get_indexing_stats()
    assert stats["analyzed"] == 0
    assert stats["pending"] == 0
    assert _open_collection(repo.working_dir).get(include=[])["ids"] == []

    # Retrying the plan completes the metadata snapshot and plans normally.
    chunks = engine.plan_indexing()
    assert calls["n"] == 2
    assert chunks
    stats = engine.get_indexing_stats()
    assert stats["pending"] == len(chunks)
    assert stats["total"] == len(chunks)


def test_poison_chunk_is_quarantined_others_reach_chroma(repo, create_config_file):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    engine = _make_engine(repo.working_dir, _PoisonEmbeddingFunction())
    clock = [0.0]
    queue, context = _make_queue(engine, clock)

    chunks = [
        _chunk("good-a", "apple pie"),
        _chunk("poison-1", "POISON"),
        _chunk("good-b", "banana bread"),
        _chunk("good-c", "cherry cake"),
    ]
    healthy_ids = {"good-a", "good-b", "good-c"}
    # Synthetic chunks are queued directly: they are not part of the current
    # repository snapshot and therefore must not inflate any stats.
    handled = []
    with _clock_patch(clock):
        queue.enqueue("get_stats", priority=HIGH_PRIORITY, wait_for_result=False)
        lane = context["lane"]
        lane.submit(
            make_batches(
                lane.project_id,
                lane.registration_id,
                lane.resource_key,
                chunks,
                4,
                chroma.chunk_metadata,
            )
        )
        _drive(queue, context, handled)

    assert handled[0][0] == "get_stats"
    # Only the scheduler's completion events follow, at high priority
    assert all(name == "index_event" for name, _ in handled[1:])
    assert all(priority == HIGH_PRIORITY for _, priority in handled[1:])
    # Everything submitted was published and acked
    assert lane.outstanding() == 0

    assert context["failed_chunks"] == {"poison-1"}
    assert not context["paused"]

    # Quarantine and completion are visible in the real vector store.
    stored = _open_collection(repo.working_dir).get(
        ids=sorted(healthy_ids | {"poison-1"}), include=[]
    )
    assert set(stored["ids"]) == healthy_ids

    # The synthetic chunks never belonged to any plan, so stats stay at zero.
    assert engine.get_indexing_stats() == {
        "analyzed": 0,
        "pending": 0,
        "total": 0,
        "failed": 0,
    }


def test_model_outage_pauses_retains_and_recovers_without_commit(
    repo, create_config_file
):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    embedding_function = _SwitchableEmbeddingFunction()
    embedding_function.fail = True
    engine = _make_engine(repo.working_dir, embedding_function)
    clock = [0.0]
    queue, context = _make_queue(engine, clock)
    lane = context["lane"]
    context["failed_chunks"].add("seed-failed")  # must survive until recovery

    with _clock_patch(clock):
        queue.handle_maintenance(context)
        stats = engine.get_indexing_stats()
        current_pending = stats["pending"]
        assert current_pending > 0
        total_batches = math.ceil(current_pending / 4)

        # First batch embed fails, probe fails: the shared resource is down
        # and every batch is retained by the scheduler.
        _drive(queue, context)
        status = lane.status()
        assert status["paused"] and status["pause_reason"] == "embedding"
        assert status["queued"] == total_batches
        assert lane.outstanding() == total_batches
        # No quarantine: nothing was marked failed or dropped from pending.
        assert context["failed_chunks"] == {"seed-failed"}
        stats = engine.get_indexing_stats()
        assert stats["pending"] == current_pending
        assert stats["analyzed"] == 0
        assert len(embedding_function.calls) == 2  # one embed + one failing probe
        # Retained batches made no further model attempts while paused.
        _drive(queue, context)
        assert len(embedding_function.calls) == 2
        assert queue.handle_get_stats(context)["indexing"]["paused"] is True

        # Still down: the retry probe fails again, work stays retained.
        clock[0] = 10.0
        _drive(queue, context)
        assert lane.status()["pause_reason"] == "embedding"
        assert len(embedding_function.calls) == 3
        assert lane.status()["queued"] == total_batches

        # Model recovers: one probe succeeds, failed ids reset, work resumes.
        embedding_function.fail = False
        clock[0] = 30.0
        _drive(queue, context)
        assert not lane.status()["paused"]
        assert context["failed_chunks"] == set()
        assert context["replan_pending"] is True
        assert len(embedding_function.calls) == 4 + total_batches  # probe + batches
        stats = engine.get_indexing_stats()
        assert stats["analyzed"] == current_pending
        assert stats["pending"] == 0
        assert lane.outstanding() == 0

        # A failed planning attempt must preserve the replan flag.
        clock[0] = 50.0
        original_plan = engine.plan_indexing
        plan_calls = {"n": 0}

        def failing_plan(excluded_ids=frozenset()):
            plan_calls["n"] += 1
            if plan_calls["n"] == 1:
                raise RuntimeError("planning crashed")
            return original_plan(excluded_ids)

        engine.plan_indexing = failing_plan
        with pytest.raises(RuntimeError, match="planning crashed"):
            queue.handle_maintenance(context)
        assert context["replan_pending"] is True
        stats = engine.get_indexing_stats()
        assert stats["pending"] == 0
        assert stats["analyzed"] == current_pending

        # Next maintenance replans successfully; still no new commit anywhere.
        clock[0] = 70.0
        queue.handle_maintenance(context)
        assert context["replan_pending"] is False
        stats = engine.get_indexing_stats()
        assert stats["analyzed"] == current_pending
        assert stats["pending"] == 0

    stored = _open_collection(repo.working_dir).get(include=[])
    assert len(stored["ids"]) == current_pending


def test_storage_outage_retains_batches_and_recovers_with_matching_rows(
    repo, create_config_file
):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    engine = _make_engine(repo.working_dir, _DeterministicEmbeddingFunction())
    clock = [0.0]
    queue, context = _make_queue(engine, clock)
    lane = context["lane"]
    source = engine._fetchers["sync"][0]
    real_write_batch = source["write_batch"]
    calls = {"n": 0}

    def flaky_write_batch(ids, documents, metadatas):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("storage down")
        real_write_batch(ids, documents, metadatas)

    source["write_batch"] = flaky_write_batch

    with _clock_patch(clock):
        queue.handle_maintenance(context)
        stats = engine.get_indexing_stats()
        current_pending = stats["pending"]
        assert current_pending > 0
        total_batches = math.ceil(current_pending / 4)

        # Pending counts must include queued work...
        before = queue.handle_get_stats(context)
        assert before["chunks"]["unanalyzed"] == current_pending
        assert before["chunks"]["analyzed"] == 0
        assert before["indexing"]["queued"] == total_batches
        # ...and must not report 100 percent immediately after submission.
        assert before["accuracy"]["percentage"] != 100

        # Whole batches retained: no quarantine, no immediate retry storm.
        _drive(queue, context)
        status = lane.status()
        assert status["paused"] and status["pause_reason"] == "storage"
        assert context["failed_chunks"] == set()
        assert status["queued"] == total_batches
        stats = engine.get_indexing_stats()
        assert stats["pending"] == current_pending
        assert _open_collection(repo.working_dir).get(include=[])["ids"] == []

        # Everything still counted as pending while paused.
        paused = queue.handle_get_stats(context)
        assert paused["indexing"]["paused"] is True
        assert paused["indexing"]["pause_reason"] == "storage"
        assert paused["chunks"]["unanalyzed"] == current_pending
        assert paused["accuracy"]["percentage"] != 100

        # Before the retry deadline nothing is re-attempted.
        clock[0] = 5.0
        _drive(queue, context)
        assert lane.status()["queued"] == total_batches
        assert _open_collection(repo.working_dir).get(include=[])["ids"] == []
        assert calls["n"] == 1  # exactly one storage attempt so far

        # Past the deadline with storage restored, the retained batches run.
        clock[0] = 30.0
        _drive(queue, context)
        assert not lane.status()["paused"]
        assert context["failed_chunks"] == set()
        stats = engine.get_indexing_stats()
        assert stats["analyzed"] == current_pending
        assert stats["pending"] == 0
        stored = _open_collection(repo.working_dir).get(include=[])
        assert len(stored["ids"]) == current_pending

        # Maintenance after success: paused stays clear and stats reflect 100%.
        clock[0] = 50.0
        queue.handle_maintenance(context)
        done = queue.handle_get_stats(context)
        assert done["indexing"]["paused"] is False
        assert done["chunks"]["unanalyzed"] == 0
        assert done["chunks"]["analyzed"] == current_pending
        assert done["accuracy"]["percentage"] == 100
