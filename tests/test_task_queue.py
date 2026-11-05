"""Behavioural tests for seagoat.queue.task_queue.

These cover the indexing queue: when maintenance runs, when it is skipped,
how chunks are analyzed by the worker thread, what query/status tasks return,
and the reported accuracy of the index.
"""

import logging
import time
from queue import PriorityQueue
from types import SimpleNamespace

import orjson
import pytest

from seagoat import __version__
from seagoat.engine import Engine
from seagoat.queue.base_queue import HIGH_PRIORITY, MEDIUM_PRIORITY, Task
from seagoat.queue.indexing_scheduler import IndexBatch, IndexingScheduler
from seagoat.queue.task_queue import (
    SECONDS_BETWEEN_MAINTENANCE,
    TaskQueue,
    calculate_accuracy,
)
from seagoat.repository import Repository
from seagoat.sources.chroma import EmbeddingError
from seagoat.utils.wait import wait_for
from tests.fixtures.scheduling import attach_lane
from tests.fixtures.sources import mock_sources_context


class QueueWithQuietWorker(TaskQueue):
    """A task queue whose worker is unable to build a context.

    The worker thread therefore idles instead of running maintenance or
    consuming tasks, letting tests drive ``handle_maintenance`` directly.
    """

    def _get_context(self):
        raise RuntimeError("worker disabled for direct-handler tests")


def _quiet_queue(repo, **kwargs):
    queue = QueueWithQuietWorker(repo_path=repo.working_dir, **kwargs)
    queue.shutdown()
    return queue


def _engine_context(repo, queue):
    context = {
        "seagoat_engine": Engine(repo.working_dir),
        "last_maintenance": None,
        "last_repo_state_hash": None,
    }
    attach_lane(queue, context)
    return context


def _chunk_ids_of(repo):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    return {
        chunk.chunk_id
        for file, _ in repository.top_files()
        for chunk in file.get_chunks()
    }


def test_maintenance_is_skipped_when_it_ran_recently(repo, mocker):
    queue = _quiet_queue(repo)
    context = _engine_context(repo, queue)
    context["last_maintenance"] = time.monotonic()
    engine = context["seagoat_engine"]
    spy_plan = mocker.spy(engine, "plan_indexing")
    spy_status_hash = mocker.spy(engine.repository, "get_status_hash")

    queue.handle_maintenance(context)

    # Neither the repo state check nor the analysis runs at all.
    assert spy_status_hash.call_count == 0
    assert spy_plan.call_count == 0


def test_maintenance_is_skipped_when_repository_is_unchanged(repo, mocker):
    queue = _quiet_queue(repo)
    context = _engine_context(repo, queue)
    context["last_repo_state_hash"] = context[
        "seagoat_engine"
    ].repository.get_status_hash()
    spy_plan = mocker.spy(context["seagoat_engine"], "plan_indexing")

    queue.handle_maintenance(context)

    assert spy_plan.call_count == 0


def test_maintenance_is_skipped_while_chunk_tasks_are_queued(repo, mocker):
    """A queued prune task defers maintenance only for an unchanged repo."""
    queue = _quiet_queue(repo)
    context = _engine_context(repo, queue)
    context["last_repo_state_hash"] = context[
        "seagoat_engine"
    ].repository.get_status_hash()
    queue._task_queue.put(Task(priority=HIGH_PRIORITY, name="prune_index"))
    spy_plan = mocker.spy(context["seagoat_engine"], "plan_indexing")

    queue.handle_maintenance(context)

    # Unchanged repository: no replan, no replace, no scheduler queue changes
    assert spy_plan.call_count == 0
    assert context["lane"].status()["queued"] == 0


def test_maintenance_logs_when_all_chunks_are_analyzed(repo, caplog):
    with mock_sources_context(repo, {}, {}):
        queue = _quiet_queue(repo)
        engine = Engine(repo.working_dir)
        # Analyze the entire repository up front (outside the queue).
        assert engine.analyze_codebase(minimum_chunks_to_analyze=10_000) == []
        context = {
            "seagoat_engine": engine,
            "last_maintenance": None,
            "last_repo_state_hash": None,
        }
        attach_lane(queue, context)

        with caplog.at_level(logging.INFO):
            queue.handle_maintenance(context)

    assert any("Analyzed all chunks!" in record.message for record in caplog.records)


def test_real_worker_indexes_all_enqueued_chunks(repo, caplog):
    with mock_sources_context(repo, {}, {}) as (chroma_source, _):
        expected_chunk_ids = _chunk_ids_of(repo)

        task_queue = TaskQueue(repo_path=repo.working_dir)

        # Chroma (here the in-memory mock store) is the durable authority;
        # readiness means every expected chunk actually has a stored row.
        def all_chunks_analyzed():
            return expected_chunk_ids <= chroma_source["indexed_ids"](
                list(expected_chunk_ids)
            )

        try:
            with caplog.at_level(logging.INFO):
                wait_for(all_chunks_analyzed, 30)
        finally:
            task_queue.shutdown()

        final_ids = chroma_source["indexed_ids"](list(expected_chunk_ids))

    assert final_ids == expected_chunk_ids
    assert any("Processing chunk" in record.message for record in caplog.records)
    assert any("Analyzed all chunks!" in record.message for record in caplog.records)


def test_query_task_returns_serialized_results(repo):
    with mock_sources_context(
        repo,
        ripgrep_lines={"file1.md": [(1, 0.2)]},
        chroma_lines={},
    ):
        task_queue = TaskQueue(repo_path=repo.working_dir)
        try:
            payload = task_queue.enqueue(
                "query",
                query="hello",
                limit_clue=100,
                context_above=1,
                context_below=1,
            )
        finally:
            task_queue.shutdown()

    assert payload is not None
    response = orjson.loads(payload)
    assert response["version"] == __version__
    assert [result["path"] for result in response["results"]] == ["file1.md"]
    assert response["results"][0]["blocks"][0]["lines"][0]["line"] == 1


def test_stats_task_counts_analyzed_and_unanalyzed_chunks(repo):
    with mock_sources_context(repo, {}, {}) as (chroma_source, _):
        engine = Engine(repo.working_dir)
        chunks = engine.analyze_codebase(minimum_chunks_to_analyze=10_000)
        assert chunks == []
        total = engine.get_indexing_stats()["analyzed"]
        assert total > 0

        # Simulate a chunk that was never processed: delete its durable row,
        # then replan so the cheap in-memory pending counter sees it again.
        pending_chunk = next(
            chunk
            for file, _ in engine.repository.top_files()
            for chunk in file.get_chunks()
        )
        chroma_source["delete_ids"]([pending_chunk.chunk_id])
        engine.plan_indexing()
        stats = engine.get_indexing_stats()
        assert stats["pending"] == 1
        assert stats["analyzed"] == total - 1

        queue = _quiet_queue(repo)
        context = _engine_context(repo, queue)
        context["seagoat_engine"] = engine

        stats = queue.handle_get_stats(context)

    assert stats["chunks"]["unanalyzed"] == 1
    assert stats["chunks"]["analyzed"] == total - 1
    assert stats["queue"]["size"] == 0
    assert stats["accuracy"]["percentage"] > 0
    assert stats["accuracy"]["percentage"] < 100


def test_accuracy_is_100_percent_when_no_chunks_or_all_analyzed():
    assert calculate_accuracy(chunks_analyzed=0, total_chunks=0) == 100
    assert calculate_accuracy(chunks_analyzed=42, total_chunks=42) == 100
    assert calculate_accuracy(chunks_analyzed=0, total_chunks=100) == 0
    assert 0 < calculate_accuracy(chunks_analyzed=30, total_chunks=100) < 100


def _queue_without_worker(engine):
    """A TaskQueue whose maintenance can be called step by step: no thread runs."""
    queue = TaskQueue.__new__(TaskQueue)
    queue.kwargs = {}
    queue._task_queue = PriorityQueue()
    engine.config = {"server": {"chroma": {"batchSize": 100}}}
    # Mock engines must report no pending prune work by default, otherwise
    # maintenance would schedule low-priority prune tasks that starve the
    # analyze tasks these tests expect to pick up.
    engine.pending_prune_count.return_value = 0
    context = {
        "seagoat_engine": engine,
        "last_maintenance": None,
        "last_repo_state_hash": None,
    }
    attach_lane(queue, context)
    return queue, context


def test_maintenance_skipped_for_pending_chunks_runs_on_the_next_pass(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.side_effect = ["edited", "edited-2"]
    engine.plan_indexing.return_value = []
    queue, context = _queue_without_worker(engine)
    context["last_repo_state_hash"] = "edited"
    clock = {"now": 100.0}
    mocker.patch(
        "seagoat.queue.task_queue.time.monotonic", side_effect=lambda: clock["now"]
    )

    # An unchanged repository is not replanned even while a prune task is queued
    queue._task_queue.put(Task(priority=MEDIUM_PRIORITY, name="prune_index"))
    queue.handle_maintenance(context)
    engine.plan_indexing.assert_not_called()

    # A changed repository replans immediately, prune task or not: the change
    # must never wait for cleanup work that runs only after the backlog drains
    clock["now"] += SECONDS_BETWEEN_MAINTENANCE + 1
    queue.handle_maintenance(context)
    engine.plan_indexing.assert_called_once()
    assert context["last_repo_state_hash"] == "edited-2"


def test_waiting_requests_do_not_block_maintenance(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "edited"
    engine.plan_indexing.return_value = []
    queue, context = _queue_without_worker(engine)

    for _ in range(3):
        queue._task_queue.put(Task(priority=HIGH_PRIORITY, name="get_stats"))
    queue.handle_maintenance(context)

    engine.plan_indexing.assert_called_once()


def test_unchanged_repository_is_not_checked_on_every_pass(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "unchanged"
    queue, context = _queue_without_worker(engine)
    context["last_repo_state_hash"] = "unchanged"

    queue.handle_maintenance(context)
    queue.handle_maintenance(context)

    # The worker idles until the maintenance deadline; the git status check
    # must still only run once per SECONDS_BETWEEN_MAINTENANCE
    engine.repository.get_status_hash.assert_called_once()
    engine.plan_indexing.assert_not_called()


def test_failed_analysis_is_retried_on_same_unchanged_repo(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "same-state"
    engine.plan_indexing.side_effect = [RuntimeError("analysis failed"), []]
    queue, context = _queue_without_worker(engine)

    clock = {"now": 100.0}
    mocker.patch(
        "seagoat.queue.task_queue.time.monotonic", side_effect=lambda: clock["now"]
    )

    with pytest.raises(RuntimeError, match="analysis failed"):
        queue.handle_maintenance(context)

    # A pass that raised must not record the repo state: the unchanged repo is
    # retried when maintenance is next allowed, instead of being skipped
    assert context["last_repo_state_hash"] is None

    clock["now"] += SECONDS_BETWEEN_MAINTENANCE + 1
    queue.handle_maintenance(context)

    assert engine.plan_indexing.call_count == 2
    assert context["last_repo_state_hash"] == "same-state"


def test_successful_unchanged_pass_is_not_analyzed_twice(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "same-state"
    engine.plan_indexing.return_value = []
    queue, context = _queue_without_worker(engine)

    clock = {"now": 100.0}
    mocker.patch(
        "seagoat.queue.task_queue.time.monotonic", side_effect=lambda: clock["now"]
    )

    queue.handle_maintenance(context)
    assert context["last_repo_state_hash"] == "same-state"

    clock["now"] += SECONDS_BETWEEN_MAINTENANCE + 1
    queue.handle_maintenance(context)

    engine.plan_indexing.assert_called_once()


def test_scheduling_failure_leaves_repo_hash_unrecorded(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "same-state"
    engine.plan_indexing.return_value = [
        SimpleNamespace(
            chunk_id="chunk-1", chunk="text", path="a.py", codeline=1, object_id="o"
        ),
    ]
    queue, context = _queue_without_worker(engine)

    real_replace = context["lane"].replace
    calls = {"count": 0}

    def flaky_replace(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("enqueue failed")
        return real_replace(*args, **kwargs)

    context["lane"].replace = flaky_replace

    clock = {"now": 100.0}
    mocker.patch(
        "seagoat.queue.task_queue.time.monotonic", side_effect=lambda: clock["now"]
    )

    with pytest.raises(RuntimeError, match="enqueue failed"):
        queue.handle_maintenance(context)

    # The state is recorded only after the scheduled work is queued, so a
    # scheduling failure must leave it retryable on the next maintenance pass
    assert context["last_repo_state_hash"] is None

    clock["now"] += SECONDS_BETWEEN_MAINTENANCE + 1
    queue.handle_maintenance(context)

    assert context["last_repo_state_hash"] == "same-state"
    assert engine.plan_indexing.call_count == 2


def test_pending_indexing_tasks_defer_the_maintenance_deadline(mocker):
    """Batch, legacy chunk and prune_index queues defer ordinary maintenance."""
    engine = mocker.Mock()
    queue, context = _queue_without_worker(engine)
    context["last_maintenance"] = time.monotonic() - SECONDS_BETWEEN_MAINTENANCE - 1

    for task_name in ("prune_index",):
        queue._task_queue.put(Task(priority=MEDIUM_PRIORITY, name=task_name))
        assert queue._has_pending_indexing_tasks()
        assert queue.get_maintenance_deadline(context) is None
        queue._task_queue.get()

    assert not queue._has_pending_indexing_tasks()
    assert queue.get_maintenance_deadline(context) is not None

    # Outstanding global jobs no longer defer ordinary maintenance: edits are
    # replanned against the running backlog instead of waiting for it to drain
    batch = IndexBatch("p", 1, "r", ("id",), ("text",), ({},), rank=0)
    context["lane"].submit([batch])
    assert queue.get_maintenance_deadline(context) is not None
    # ... but a prune task still defers it until cleanup has been consumed
    queue._task_queue.put(Task(priority=MEDIUM_PRIORITY, name="prune_index"))
    assert queue.get_maintenance_deadline(context) is None


def test_paused_context_exposes_its_own_retry_deadline(mocker):
    """A paused recovery probe runs at retry_after, never deferred to infinity."""
    engine = mocker.Mock()
    queue, context = _queue_without_worker(engine)
    context["last_maintenance"] = time.monotonic() - SECONDS_BETWEEN_MAINTENANCE - 1
    context["paused"] = True
    context["pause_reason"] = "storage"
    context["retry_after"] = time.monotonic() + 7
    # Even a queued indexing backlog must not defer the recovery probe.
    queue._task_queue.put(Task(priority=MEDIUM_PRIORITY, name="prune_index"))
    assert queue._has_pending_indexing_tasks()
    assert queue.get_maintenance_deadline(context) == pytest.approx(
        context["retry_after"]
    )


def test_worker_probes_recovery_on_retry_deadline_and_resumes(repo, mocker):
    """An outage pauses with a bounded monotonic retry deadline; recovery
    probes run at that deadline without ordinary repo checks and without
    polling, then retained work resumes."""
    scheduler = IndexingScheduler(retry_seconds=0.5)
    state = {"ok": False}

    def flaky_embedding():
        if not state["ok"]:
            raise EmbeddingError("embedding service down")

    with mock_sources_context(repo, {}, {}, embedding=flaky_embedding) as (
        chroma_source,
        _,
    ):
        probes = {"n": 0}
        real_probe = chroma_source["probe_embedding"]

        def counting_probe():
            probes["n"] += 1
            real_probe()

        chroma_source["probe_embedding"] = counting_probe

        task_queue = TaskQueue(repo_path=repo.working_dir, scheduler=scheduler)
        try:

            def stats():
                result = task_queue.enqueue("get_stats")
                assert result is not None
                return result

            wait_for(lambda: stats()["indexing"]["paused"], 30)
            probes_before = probes["n"]
            time.sleep(1.2)
            # No 0.1s polling and no busy loop while the retry deadline is in
            # the future: the probe runs at most a handful of times in 1.2s.
            assert probes["n"] - probes_before <= 4

            state["ok"] = True
            wait_for(lambda: stats()["chunks"]["unanalyzed"] == 0, 10)
            assert stats()["indexing"]["paused"] is False
            assert probes["n"] > probes_before
        finally:
            task_queue.shutdown()
            scheduler.shutdown()


def test_task_queue_maintenance_runs_under_continuous_task_load(repo, mocker):
    """Genuinely due maintenance must still run under a never-idle queue."""
    with mock_sources_context(repo, {}, {}):
        real_get_status_hash = Repository.get_status_hash
        calls = {"n": 0}

        def counting_get_status_hash(self, *args, **kwargs):
            calls["n"] += 1
            return real_get_status_hash(self, *args, **kwargs)

        mocker.patch.object(Repository, "get_status_hash", counting_get_status_hash)
        # Keep the test fast: the real 10s cadence is covered by the clocked
        # unit tests below.
        mocker.patch("seagoat.queue.task_queue.SECONDS_BETWEEN_MAINTENANCE", 0.5)
        task_queue = TaskQueue(repo_path=repo.working_dir)
        try:
            wait_for(lambda: calls["n"] >= 1, 30)  # initial maintenance
            runs_before_load = calls["n"]

            # Never let the queue go idle: maintenance may no longer run via
            # an Empty wakeup, only because it is genuinely due.
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                task_queue.enqueue("get_stats", wait_for_result=False)
                time.sleep(0.01)

            assert calls["n"] > runs_before_load
        finally:
            task_queue.shutdown()
