"""Stage 2 indexing acceptance tests.

These tests exercise Engine/queue batch indexing against the real Chroma
persistent store with deterministic fake embeddings; no models are downloaded.
Queue time is controlled through a SimpleNamespace clock patched onto the
task_queue module instead of using real sleeps.
"""

import math
from queue import Empty, PriorityQueue
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from seagoat.engine import Engine
from seagoat.queue import task_queue as task_queue_module
from seagoat.queue.base_queue import HIGH_PRIORITY, MEDIUM_PRIORITY
from seagoat.queue.task_queue import TaskQueue
from seagoat.sources import chroma
from seagoat.sources.chroma import EmbeddingError
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


def _make_queue(engine):
    queue = TaskQueue.__new__(TaskQueue)
    queue.kwargs = {}
    queue._task_queue = PriorityQueue()
    context = {
        "seagoat_engine": engine,
        "last_maintenance": None,
        "last_repo_state_hash": None,
    }
    queue._ensure_recovery_state(context)
    return queue, context


def _clock_patch(clock):
    return patch.object(
        task_queue_module,
        "time",
        SimpleNamespace(time=lambda: clock[0], monotonic=lambda: clock[0]),
    )


def _drive(queue, context, record=None):
    handled = 0
    while True:
        try:
            task = queue._task_queue.get_nowait()
        except Empty:
            return handled
        if record is not None:
            record.append((task.name, task.priority))
        queue._handle_task(context, task)
        handled += 1


def _seed_legacy_marks(engine, ids):
    engine.cache.data["chunks_already_analyzed"] = set(ids)
    engine.cache.data["chunks_not_yet_analyzed"] = set()
    engine.cache.persist()


def test_engine_indexes_all_chunks_one_persist_per_batch(repo, create_config_file):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    with patch.object(
        chroma,
        "_get_embedding_function",
        return_value=_DeterministicEmbeddingFunction(),
    ):
        engine = Engine(repo.working_dir)
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

    def recording_cache_batch(batch):
        batch_ids = {chunk.chunk_id for chunk in batch}
        assert not batch_ids & engine.cache.data["chunks_already_analyzed"]
        batch_sizes.append(len(batch_ids))
        real_cache_batch(batch)

    source["cache_batch"] = recording_cache_batch

    remaining = engine.analyze_codebase(minimum_chunks_to_analyze=len(chunks))
    assert remaining == []
    assert engine.cache.data["chunks_already_analyzed"] == current_ids
    assert engine.cache.data["chunks_not_yet_analyzed"] == set()

    stored = _open_collection(repo.working_dir).get(ids=sorted(current_ids), include=[])
    assert set(stored["ids"]) == current_ids

    expected_batches = math.ceil(len(chunks) / 4)
    assert len(persist_calls) == len(batch_sizes) == expected_batches
    full_batches, remainder = divmod(len(chunks), 4)
    expected_sizes = [4] * full_batches + ([remainder] if remainder else [])
    assert batch_sizes == expected_sizes


@pytest.mark.parametrize("limit", [1, 2, 4])
def test_analyze_codebase_explicit_limits_still_honored(
    repo, create_config_file, limit
):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    with patch.object(
        chroma,
        "_get_embedding_function",
        return_value=_DeterministicEmbeddingFunction(),
    ):
        engine = Engine(repo.working_dir)
    chunks = engine.plan_indexing()
    assert len(chunks) >= 4

    remaining = engine.analyze_codebase(minimum_chunks_to_analyze=limit)

    assert len(remaining) == len(chunks) - limit
    assert len(engine.cache.data["chunks_already_analyzed"]) == limit
    assert len(engine.cache.data["chunks_not_yet_analyzed"]) == len(chunks) - limit
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
    assert fresh.cache.data["chunks_already_analyzed"] == current_ids
    assert fresh.cache.data["chunks_not_yet_analyzed"] == set()

    pending = fresh.plan_indexing()
    assert {chunk.chunk_id for chunk in pending} == current_ids
    assert fresh.cache.data["chunks_already_analyzed"] == set()
    assert fresh.cache.data["chunks_not_yet_analyzed"] == current_ids

    fresh.analyze_codebase(minimum_chunks_to_analyze=len(pending))
    assert fresh.cache.data["chunks_already_analyzed"] == current_ids
    assert fresh.cache.data["chunks_not_yet_analyzed"] == set()

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
    assert fresh._repair_done is False
    assert fresh.cache.data["chunks_already_analyzed"] == current_ids
    assert not fresh.cache.data["chunks_not_yet_analyzed"] & current_ids

    pending = fresh.plan_indexing()
    assert calls["n"] == 2
    assert fresh._repair_done is True
    assert {chunk.chunk_id for chunk in pending} == current_ids

    fresh.analyze_codebase(minimum_chunks_to_analyze=len(pending))
    assert fresh.cache.data["chunks_already_analyzed"] == current_ids
    assert fresh.cache.data["chunks_not_yet_analyzed"] == set()
    stored = _open_collection(repo.working_dir).get(ids=sorted(current_ids), include=[])
    assert set(stored["ids"]) == current_ids


def test_embed_failure_marks_nothing_and_is_retryable(repo, create_config_file):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    embedding_function = _SwitchableEmbeddingFunction()
    embedding_function.fail = True
    engine = _make_engine(repo.working_dir, embedding_function)
    chunks = engine.plan_indexing()
    batch = chunks[:4]
    batch_ids = {chunk.chunk_id for chunk in batch}
    assert len(batch_ids) == 4

    with pytest.raises(EmbeddingError):
        engine.process_batch(batch)

    assert not batch_ids & engine.cache.data["chunks_already_analyzed"]
    assert batch_ids <= engine.cache.data["chunks_not_yet_analyzed"]
    stored = _open_collection(repo.working_dir).get(ids=sorted(batch_ids), include=[])
    assert stored["ids"] == []

    # After the model recovers the same batch succeeds and reaches storage.
    embedding_function.fail = False
    engine.process_batch(batch)
    assert batch_ids <= engine.cache.data["chunks_already_analyzed"]
    assert not batch_ids & engine.cache.data["chunks_not_yet_analyzed"]
    stored = _open_collection(repo.working_dir).get(ids=sorted(batch_ids), include=[])
    assert set(stored["ids"]) == batch_ids


def test_persist_failure_after_upsert_keeps_retryable_state(repo, create_config_file):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    engine = _make_engine(repo.working_dir, _DeterministicEmbeddingFunction())
    chunks = engine.plan_indexing()
    batch = chunks[:4]
    batch_ids = {chunk.chunk_id for chunk in batch}

    original_persist = engine.cache.persist
    calls = {"n": 0}

    def flaky_persist():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        original_persist()

    engine.cache.persist = flaky_persist

    with pytest.raises(OSError, match="disk full"):
        engine.process_batch(batch)

    # Vectors were written but the completion record was not: the IDs must
    # stay retryable and must not be marked analyzed.
    assert not batch_ids & engine.cache.data["chunks_already_analyzed"]
    assert batch_ids <= engine.cache.data["chunks_not_yet_analyzed"]

    engine.process_batch(batch)
    assert calls["n"] == 2
    assert batch_ids <= engine.cache.data["chunks_already_analyzed"]
    assert not batch_ids & engine.cache.data["chunks_not_yet_analyzed"]

    stored = _open_collection(repo.working_dir).get(ids=sorted(batch_ids), include=[])
    assert set(stored["ids"]) == batch_ids
    assert len(stored["ids"]) == len(batch_ids)  # upsert replaced, no duplicates


def test_poison_chunk_is_quarantined_others_reach_chroma(repo, create_config_file):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    engine = _make_engine(repo.working_dir, _PoisonEmbeddingFunction())
    queue, context = _make_queue(engine)
    clock = [0.0]

    chunks = [
        _chunk("good-a", "apple pie"),
        _chunk("poison-1", "POISON"),
        _chunk("good-b", "banana bread"),
        _chunk("good-c", "cherry cake"),
    ]
    healthy_ids = {"good-a", "good-b", "good-c"}
    # Simulate the work planned by a maintenance pass for these synthetic IDs.
    engine.cache.data["chunks_not_yet_analyzed"].update(
        chunk.chunk_id for chunk in chunks
    )

    handled = []
    with _clock_patch(clock):
        # A priority-zero user task queued before the batch must run first.
        queue.enqueue("get_stats", priority=HIGH_PRIORITY, wait_for_result=False)
        queue._enqueue_batch(chunks, MEDIUM_PRIORITY)
        _drive(queue, context, handled)

    assert handled[0][0] == "get_stats"
    assert all(name == "analyze_batch" for name, _ in handled[1:])
    assert all(priority == MEDIUM_PRIORITY for _, priority in handled[1:])

    assert context["failed_chunks"] == {"poison-1"}
    assert "poison-1" not in engine.cache.data["chunks_not_yet_analyzed"]
    assert engine.cache.data["chunks_already_analyzed"] == healthy_ids
    assert engine.cache.data["chunks_not_yet_analyzed"] == set()
    assert not context["paused"]

    stored = _open_collection(repo.working_dir).get(
        ids=sorted(healthy_ids | {"poison-1"}), include=[]
    )
    assert set(stored["ids"]) == healthy_ids


def test_model_outage_pauses_retains_and_recovers_without_commit(
    repo, create_config_file
):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    embedding_function = _SwitchableEmbeddingFunction()
    embedding_function.fail = True
    engine = _make_engine(repo.working_dir, embedding_function)
    queue, context = _make_queue(engine)
    clock = [0.0]
    context["failed_chunks"].add("seed-failed")  # must survive until recovery

    with _clock_patch(clock):
        queue.handle_maintenance(context)
        current_ids = set(engine.cache.data["chunks_not_yet_analyzed"])
        assert current_ids
        total_batches = math.ceil(len(current_ids) / 4)

        # First batch embed fails, probe fails: pause, retain everything.
        _drive(queue, context)
        assert context["paused"] and context["pause_reason"] == "embedding"
        assert len(context["retained_batches"]) == total_batches
        assert sum(len(c) for c, _, _ in context["retained_batches"]) == len(
            current_ids
        )
        # No quarantine: nothing was marked failed or dropped from pending.
        assert context["failed_chunks"] == {"seed-failed"}
        assert engine.cache.data["chunks_not_yet_analyzed"] == current_ids
        assert len(embedding_function.calls) == 2  # one embed + one failing probe
        # Retained/queued indices made no further model attempts while paused.
        _drive(queue, context)
        assert len(embedding_function.calls) == 2

        # Still down: the retry probe fails again, work stays retained.
        clock[0] = 10.0
        queue.handle_maintenance(context)
        assert context["paused"] and context["pause_reason"] == "embedding"
        assert len(embedding_function.calls) == 3
        assert sum(len(c) for c, _, _ in context["retained_batches"]) == len(
            current_ids
        )
        assert engine.cache.data["chunks_not_yet_analyzed"] == current_ids

        # Model recovers: probe succeeds, failed ids reset, retained re-enqueued.
        embedding_function.fail = False
        clock[0] = 30.0
        queue.handle_maintenance(context)
        assert not context["paused"]
        assert context["failed_chunks"] == set()
        assert context["replan_pending"] is True
        assert len(embedding_function.calls) == 4  # the successful probe only

        _drive(queue, context)
        assert engine.cache.data["chunks_already_analyzed"] == current_ids
        assert engine.cache.data["chunks_not_yet_analyzed"] == set()

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
        assert engine.cache.data["chunks_not_yet_analyzed"] == set()

        # Next maintenance replans successfully; still no new commit anywhere.
        clock[0] = 70.0
        queue.handle_maintenance(context)
        assert context["replan_pending"] is False
        assert engine.cache.data["chunks_already_analyzed"] == current_ids
        assert engine.cache.data["chunks_not_yet_analyzed"] == set()

    stored = _open_collection(repo.working_dir).get(ids=sorted(current_ids), include=[])
    assert set(stored["ids"]) == current_ids


def test_storage_outage_retains_batches_and_recovers_with_matching_rows(
    repo, create_config_file
):
    create_config_file({"server": {"chroma": {"batchSize": 4}}})
    engine = _make_engine(repo.working_dir, _DeterministicEmbeddingFunction())
    queue, context = _make_queue(engine)
    clock = [0.0]
    source = engine._fetchers["sync"][0]
    real_cache_batch = source["cache_batch"]
    calls = {"n": 0}

    def flaky_cache_batch(batch):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("storage down")
        real_cache_batch(batch)

    source["cache_batch"] = flaky_cache_batch

    with _clock_patch(clock):
        queue.handle_maintenance(context)
        current_ids = set(engine.cache.data["chunks_not_yet_analyzed"])
        assert current_ids

        # Pending counts must include queued AND retained work...
        before = queue.handle_get_stats(context)
        assert before["chunks"]["unanalyzed"] == len(current_ids)
        assert before["chunks"]["analyzed"] == 0
        # ...and must not report 100 percent immediately after enqueue.
        assert before["accuracy"]["percentage"] != 100

        # Whole batches retained: no quarantine, no immediate retry storm.
        _drive(queue, context)
        assert context["paused"] and context["pause_reason"] == "storage"
        assert context["failed_chunks"] == set()
        retained_ids = {
            chunk.chunk_id
            for batch, _, _ in context["retained_batches"]
            for chunk in batch
        }
        assert retained_ids == current_ids
        assert len(context["retained_batches"]) == math.ceil(len(current_ids) / 4)
        assert engine.cache.data["chunks_not_yet_analyzed"] == current_ids
        assert _open_collection(repo.working_dir).get(include=[])["ids"] == []

        # Everything still counted as pending while paused.
        paused = queue.handle_get_stats(context)
        assert paused["indexing"]["paused"] is True
        assert paused["chunks"]["unanalyzed"] == len(current_ids)
        assert paused["accuracy"]["percentage"] != 100

        # Before the retry deadline nothing is re-attempted: still paused,
        # work still retained, storage untouched.
        clock[0] = 5.0
        queue.handle_maintenance(context)
        assert context["paused"] and context["pause_reason"] == "storage"
        assert len(context["retained_batches"]) == math.ceil(len(current_ids) / 4)
        assert _open_collection(repo.working_dir).get(include=[])["ids"] == []
        assert engine.cache.data["chunks_not_yet_analyzed"] == current_ids
        assert calls["n"] == 1  # exactly one storage attempt so far

        # Past the deadline with storage restored, recovery re-enqueues the
        # retained batches; drive completes them with no quarantine.
        clock[0] = 30.0
        queue.handle_maintenance(context)
        assert not context["paused"]
        assert context["replan_pending"] is True
        assert context["retained_batches"] == []
        assert context["failed_chunks"] == set()
        _drive(queue, context)

        assert engine.cache.data["chunks_already_analyzed"] == current_ids
        assert engine.cache.data["chunks_not_yet_analyzed"] == set()
        stored = _open_collection(repo.working_dir).get(
            ids=sorted(current_ids), include=[]
        )
        assert set(stored["ids"]) == current_ids

        # Maintenance after success: paused stays clear and stats reflect 100%.
        clock[0] = 50.0
        queue.handle_maintenance(context)
        assert not context["paused"]
        done = queue.handle_get_stats(context)
        assert done["chunks"]["unanalyzed"] == 0
        assert done["chunks"]["analyzed"] == len(current_ids)
        assert done["accuracy"]["percentage"] == 100
