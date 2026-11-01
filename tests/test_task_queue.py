"""Behavioural tests for seagoat.queue.task_queue.

These cover the indexing queue: when maintenance runs, when it is skipped,
how chunks are analyzed by the worker thread, what query/status tasks return,
and the reported accuracy of the index.
"""

import logging
import time
from queue import PriorityQueue

import orjson
import pytest

from seagoat import __version__
from seagoat.engine import Engine
from seagoat.queue.base_queue import HIGH_PRIORITY, MEDIUM_PRIORITY, Task
from seagoat.queue.task_queue import (
    SECONDS_BETWEEN_MAINTENANCE,
    TaskQueue,
    calculate_accuracy,
)
from seagoat.repository import Repository
from seagoat.utils.wait import wait_for
from tests.fixtures.sources import mock_sources_context


class QueueWithQuietWorker(TaskQueue):
    """A task queue whose worker is unable to build a context.

    The worker thread therefore idles instead of running maintenance or
    consuming tasks, letting tests drive ``handle_maintenance`` directly.
    """

    def _get_context(self):
        raise RuntimeError("worker disabled for direct-handler tests")


def _quiet_queue(repo, **kwargs):
    kwargs.setdefault("minimum_chunks_to_analyze", 0)
    queue = QueueWithQuietWorker(repo_path=repo.working_dir, **kwargs)
    queue.shutdown()
    return queue


def _engine_context(repo):
    return {
        "seagoat_engine": Engine(repo.working_dir),
        "last_maintenance": None,
        "last_repo_state_hash": None,
    }


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
    context = _engine_context(repo)
    context["last_maintenance"] = time.time()
    engine = context["seagoat_engine"]
    spy_analyze = mocker.spy(engine, "analyze_codebase")
    spy_status_hash = mocker.spy(engine.repository, "get_status_hash")

    queue.handle_maintenance(context)

    # Neither the repo state check nor the analysis runs at all.
    assert spy_status_hash.call_count == 0
    assert spy_analyze.call_count == 0


def test_maintenance_is_skipped_when_repository_is_unchanged(repo, mocker):
    queue = _quiet_queue(repo)
    context = _engine_context(repo)
    context["last_repo_state_hash"] = context[
        "seagoat_engine"
    ].repository.get_status_hash()
    spy_analyze = mocker.spy(context["seagoat_engine"], "analyze_codebase")

    queue.handle_maintenance(context)

    assert spy_analyze.call_count == 0


def test_maintenance_is_skipped_while_chunk_tasks_are_queued(repo, mocker):
    queue = _quiet_queue(repo)
    context = _engine_context(repo)
    queue._task_queue.put(
        Task(priority=HIGH_PRIORITY, name="analyze_chunk", args=("fake chunk",))
    )
    spy_analyze = mocker.spy(context["seagoat_engine"], "analyze_codebase")

    queue.handle_maintenance(context)

    assert spy_analyze.call_count == 0


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

        with caplog.at_level(logging.INFO):
            queue.handle_maintenance(context)

    assert any("Analyzed all chunks!" in record.message for record in caplog.records)


def test_real_worker_indexes_all_enqueued_chunks(repo, caplog):
    with mock_sources_context(repo, {}, {}):
        expected_chunk_ids = _chunk_ids_of(repo)

        task_queue = TaskQueue(repo_path=repo.working_dir, minimum_chunks_to_analyze=0)
        observer = Engine(repo.working_dir)

        def all_chunks_analyzed():
            observer.cache.load()
            return expected_chunk_ids <= observer.cache.data["chunks_already_analyzed"]

        try:
            with caplog.at_level(logging.INFO):
                wait_for(all_chunks_analyzed, 30)
        finally:
            task_queue.shutdown()

        final_state = Engine(repo.working_dir)
        assert final_state.cache.data["chunks_not_yet_analyzed"] == set()

    assert not expected_chunk_ids - final_state.cache.data["chunks_already_analyzed"]
    assert any("Processing chunk" in record.message for record in caplog.records)
    assert any("Analyzed all chunks!" in record.message for record in caplog.records)


def test_query_task_returns_serialized_results(repo):
    with mock_sources_context(
        repo,
        ripgrep_lines={"file1.md": [(1, 0.2)]},
        chroma_lines={},
    ):
        task_queue = TaskQueue(repo_path=repo.working_dir, minimum_chunks_to_analyze=0)
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
    with mock_sources_context(repo, {}, {}):
        engine = Engine(repo.working_dir)
        chunks = engine.analyze_codebase(minimum_chunks_to_analyze=10_000)
        assert chunks == []

        # A chunk that was never processed is reported as unanalyzed.
        pending_chunk = next(
            chunk
            for file, _ in engine.repository.top_files()
            for chunk in file.get_chunks()
        )
        engine.cache.data["chunks_already_analyzed"].discard(pending_chunk.chunk_id)
        engine.cache.data["chunks_not_yet_analyzed"].add(pending_chunk.chunk_id)

        queue = _quiet_queue(repo)
        context = _engine_context(repo)
        context["seagoat_engine"] = engine

        stats = queue.handle_get_stats(context)

    total = stats["chunks"]["analyzed"] + stats["chunks"]["unanalyzed"]
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
    queue.kwargs = {"minimum_chunks_to_analyze": 0}
    queue._task_queue = PriorityQueue()
    context = {
        "seagoat_engine": engine,
        "last_maintenance": None,
        "last_repo_state_hash": None,
    }
    return queue, context


def test_maintenance_skipped_for_pending_chunks_runs_on_the_next_pass(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "edited"
    engine.analyze_codebase.return_value = []
    queue, context = _queue_without_worker(engine)

    queue._task_queue.put(Task(priority=MEDIUM_PRIORITY, name="analyze_chunk"))
    queue.handle_maintenance(context)
    engine.analyze_codebase.assert_not_called()

    # Once the chunks are processed, the same (unchanged) repo state must still
    # be analyzed: the skipped pass must not have recorded it as done
    queue._task_queue.get()
    queue.handle_maintenance(context)
    engine.analyze_codebase.assert_called_once()


def test_waiting_requests_do_not_block_maintenance(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "edited"
    engine.analyze_codebase.return_value = []
    queue, context = _queue_without_worker(engine)

    for _ in range(3):
        queue._task_queue.put(Task(priority=HIGH_PRIORITY, name="get_stats"))
    queue.handle_maintenance(context)

    engine.analyze_codebase.assert_called_once()


def test_unchanged_repository_is_not_checked_on_every_pass(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "unchanged"
    queue, context = _queue_without_worker(engine)
    context["last_repo_state_hash"] = "unchanged"

    queue.handle_maintenance(context)
    queue.handle_maintenance(context)

    # The worker calls maintenance every 0.1s when idle; the git status check
    # must still only run once per SECONDS_BETWEEN_MAINTENANCE
    engine.repository.get_status_hash.assert_called_once()
    engine.analyze_codebase.assert_not_called()


def test_failed_analysis_is_retried_on_same_unchanged_repo(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "same-state"
    engine.analyze_codebase.side_effect = [RuntimeError("analysis failed"), []]
    queue, context = _queue_without_worker(engine)

    clock = {"now": 100.0}
    mocker.patch("seagoat.queue.task_queue.time.time", side_effect=lambda: clock["now"])

    with pytest.raises(RuntimeError, match="analysis failed"):
        queue.handle_maintenance(context)

    # A pass that raised must not record the repo state: the unchanged repo is
    # retried when maintenance is next allowed, instead of being skipped
    assert context["last_repo_state_hash"] is None

    clock["now"] += SECONDS_BETWEEN_MAINTENANCE + 1
    queue.handle_maintenance(context)

    assert engine.analyze_codebase.call_count == 2
    assert context["last_repo_state_hash"] == "same-state"


def test_successful_unchanged_pass_is_not_analyzed_twice(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "same-state"
    engine.analyze_codebase.return_value = []
    queue, context = _queue_without_worker(engine)

    clock = {"now": 100.0}
    mocker.patch("seagoat.queue.task_queue.time.time", side_effect=lambda: clock["now"])

    queue.handle_maintenance(context)
    assert context["last_repo_state_hash"] == "same-state"

    clock["now"] += SECONDS_BETWEEN_MAINTENANCE + 1
    queue.handle_maintenance(context)

    engine.analyze_codebase.assert_called_once()


def test_scheduling_failure_leaves_repo_hash_unrecorded(mocker):
    engine = mocker.Mock()
    engine.repository.get_status_hash.return_value = "same-state"
    engine.analyze_codebase.return_value = [{"chunk_id": "chunk-1"}]
    queue, context = _queue_without_worker(engine)

    real_enqueue = queue.enqueue
    calls = {"count": 0}

    def flaky_enqueue(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("enqueue failed")
        return real_enqueue(*args, **kwargs)

    queue.enqueue = flaky_enqueue

    clock = {"now": 100.0}
    mocker.patch("seagoat.queue.task_queue.time.time", side_effect=lambda: clock["now"])

    with pytest.raises(RuntimeError, match="enqueue failed"):
        queue.handle_maintenance(context)

    # The state is recorded only after the scheduled work is queued, so a
    # scheduling failure must leave it retryable on the next maintenance pass
    assert context["last_repo_state_hash"] is None

    clock["now"] += SECONDS_BETWEEN_MAINTENANCE + 1
    queue.handle_maintenance(context)

    assert context["last_repo_state_hash"] == "same-state"
    assert engine.analyze_codebase.call_count == 2
