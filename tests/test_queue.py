import threading
import time
from queue import PriorityQueue
from unittest.mock import Mock, patch

import pytest

from seagoat.queue.base_queue import (
    HIGH_PRIORITY,
    LOW_PRIORITY,
    MEDIUM_PRIORITY,
    BaseQueue,
    Task,
    TaskFailed,
    TaskTimedOut,
)
from seagoat.queue.task_queue import TaskQueue
from seagoat.repository import Repository


@pytest.fixture(name="create_task_queue")
def create_task_queue(repo):
    def _create_task_queue():
        return TaskQueue(repo_path=repo.working_dir, minimum_chunks_to_analyze=0)

    return _create_task_queue


@pytest.mark.parametrize(
    "chunks_analyzed, unanalyzed, expected_accuracy",
    [
        (0, 0, 100),
        (1, 999999, 1),
        (1000, 0, 100),
        (0, 20, 0),
        (5, 150, 2),
        (50, 450, 11),
        (5, 15, 45),
        (10, 10, 91),
        (100, 100, 91),
        (100_000, 100_001, 91),
        (15, 5, 99),
        (150, 5, 99),
        (150_000, 5, 99),
    ],
)
def test_handle_get_stats(
    create_task_queue, chunks_analyzed, unanalyzed, expected_accuracy
):
    task_queue = create_task_queue()
    context = {
        "seagoat_engine": Mock(),
    }

    context["seagoat_engine"].cache.data = {
        "chunks_already_analyzed": set(range(chunks_analyzed)),
        "chunks_not_yet_analyzed": set(range(unanalyzed)),
    }

    stats = task_queue.handle_get_stats(context)
    task_queue.shutdown()

    assert stats["accuracy"]["percentage"] == expected_accuracy


def test_important_files_are_analyzed_first(create_task_queue, mocker, repo):
    enqueue = mocker.patch("seagoat.queue.task_queue.TaskQueue.enqueue")
    first_maintenance_done = threading.Event()
    original_maintenance = TaskQueue.handle_maintenance

    def tracked_maintenance(self, context):
        try:
            original_maintenance(self, context)
        finally:
            first_maintenance_done.set()

    mocker.patch.object(TaskQueue, "handle_maintenance", tracked_maintenance)
    task_queue = create_task_queue()
    # Maintenance enqueues every chunk in one pass, so waiting for its
    # first run is waiting for the whole enqueue order to exist
    assert first_maintenance_done.wait(timeout=30)
    task_queue.shutdown()
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    order_of_files_analyzed = []
    for call in enqueue.mock_calls:
        path = call.args[1].path
        if not order_of_files_analyzed or order_of_files_analyzed[-1] != path:
            order_of_files_analyzed.append(path)

    # due to sorting by file priority, chunks of the same file should
    # be grouped together
    assert len(set(order_of_files_analyzed)) == len(order_of_files_analyzed)

    # the exact order of files should also match the priority list
    assert [file.path for file, _ in repository.top_files()] == order_of_files_analyzed


def test_worker_keeps_running_when_context_fails_to_build():
    class BrokenContextQueue(BaseQueue):
        def _get_context(self):
            raise RuntimeError("context init exploded")

    queue = BrokenContextQueue()
    try:
        with pytest.raises(TaskFailed, match="context init exploded"):
            queue.enqueue("any_task")
    finally:
        queue.shutdown()


def test_worker_keeps_running_after_a_task_fails(repo):
    class FlakyQueue(BaseQueue):
        def handle_fail(self, _context):
            raise ValueError("boom")

        def handle_echo(self, _context, value):
            return value

    queue = FlakyQueue()
    try:
        with pytest.raises(TaskFailed, match="fail failed: boom"):
            queue.enqueue("fail")

        assert queue.enqueue("echo", "still alive") == "still alive"
    finally:
        queue.shutdown()


def test_enqueue_raises_task_timed_out_when_handler_blocks(mocker):
    release = threading.Event()

    class BusyQueue(BaseQueue):
        def handle_block(self, _context):
            release.wait(timeout=30)
            return "late result"

    queue = BusyQueue()
    try:
        mocker.patch("seagoat.queue.base_queue.TASK_TIMEOUT_SECONDS", 0.1)
        with pytest.raises(TaskTimedOut):
            queue.enqueue("block")
    finally:
        release.set()
        queue.shutdown()


def test_late_result_from_timed_out_task_is_dropped():
    release = threading.Event()

    class BusyQueue(BaseQueue):
        def handle_block(self, _context):
            release.wait(timeout=30)
            return "late result"

        def handle_echo(self, _context, value):
            return value

    queue = BusyQueue()
    try:
        with (
            patch("seagoat.queue.base_queue.TASK_TIMEOUT_SECONDS", 0.1),
            pytest.raises(TaskTimedOut),
        ):
            queue.enqueue("block")

        # The single worker finishes the blocked task (producing the late
        # result) before it runs echo, so echo must get its own result.
        release.set()
        assert queue.enqueue("echo", "fresh result") == "fresh result"
    finally:
        release.set()
        queue.shutdown()


def test_maintenance_runs_even_when_queue_is_busy():
    maintenance_runs = 0

    class BusyQueue(BaseQueue):
        def handle_echo(self, _context, value):
            # Keep the worker busy longer than the enqueue interval so the
            # queue never empties and the idle maintenance path cannot run.
            time.sleep(0.03)
            return value

        def handle_maintenance(self, context):
            nonlocal maintenance_runs
            maintenance_runs += 1

    queue = BusyQueue()
    try:
        # Wait for the initial idle maintenance run (the queue is empty at
        # startup), then flood the queue so it never goes idle again.
        deadline = time.monotonic() + 5
        while maintenance_runs == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert maintenance_runs >= 1

        runs_before_busy_period = maintenance_runs
        busy_deadline = time.monotonic() + 2
        while time.monotonic() < busy_deadline:
            queue.enqueue("echo", "ping", wait_for_result=False)
            time.sleep(0.02)

        assert maintenance_runs > runs_before_busy_period
    finally:
        queue.shutdown()


def test_task_id_defaults_to_a_unique_uuid_identity():
    # The task_id is still generated from a UUID even though it no longer
    # participates in Task ordering.
    first = Task(priority=HIGH_PRIORITY, name="search")
    second = Task(priority=HIGH_PRIORITY, name="search")
    assert first.task_id != second.task_id
    assert len(first.task_id) == 32
    assert len(second.task_id) == 32
    assert all(c in "0123456789abcdef" for c in first.task_id)


def test_same_name_equal_priority_tasks_run_in_fifo_order():
    # Explicit task_ids make the pre-fix (name, task_id) ordering pick the
    # second task first; FIFO must pick the first task regardless of ID.
    queue = PriorityQueue()
    first = Task(priority=MEDIUM_PRIORITY, name="search", task_id="zzzzzzzz")
    second = Task(priority=MEDIUM_PRIORITY, name="search", task_id="aaaaaaaa")
    queue.put(first)
    queue.put(second)

    assert queue.get_nowait() is first
    assert queue.get_nowait() is second
    # explicit ids stay available and do not leak into FIFO ordering
    assert first.task_id == "zzzzzzzz"
    assert second.task_id == "aaaaaaaa"


def test_mixed_get_stats_and_query_equal_priority_tasks_run_in_fifo_order():
    # Pre-fix, equal-priority tasks were ordered by task name, so a "query"
    # task enqueued first would be leapfrogged by "get_stats".
    queue = PriorityQueue()
    query = Task(priority=HIGH_PRIORITY, name="query")
    get_stats = Task(priority=HIGH_PRIORITY, name="get_stats")
    queue.put(query)
    queue.put(get_stats)

    assert queue.get_nowait() is query
    assert queue.get_nowait() is get_stats


def test_higher_priority_task_wins_over_fifo_order():
    # A later-enqueued higher-priority task still runs first even though the
    # FIFO sequence would otherwise put the earlier task ahead.
    queue = PriorityQueue()
    low = Task(priority=LOW_PRIORITY, name="search")
    high = Task(priority=MEDIUM_PRIORITY, name="search")
    queue.put(low)
    queue.put(high)

    assert queue.get_nowait() is high
    assert queue.get_nowait() is low


def test_worker_runs_equal_priority_tasks_in_fifo_order():
    handled = []
    gate_started = threading.Event()
    release_gate = threading.Event()

    class RecordingQueue(BaseQueue):
        def handle_gate(self, _context):
            gate_started.set()
            release_gate.wait(timeout=30)

        def handle_record(self, _context, value):
            handled.append(value)

    queue = RecordingQueue()
    try:
        queue._task_queue.put(Task(priority=HIGH_PRIORITY, name="gate"))
        assert gate_started.wait(timeout=30)
        # The worker is blocked on the gate, so both tasks are queued before
        # either is picked; no enqueue timing can hide the queue's ordering.
        queue._task_queue.put(
            Task(
                priority=HIGH_PRIORITY,
                name="record",
                args=("first",),
                task_id="zzzzzzzz",
            )
        )
        queue._task_queue.put(
            Task(
                priority=HIGH_PRIORITY,
                name="record",
                args=("second",),
                task_id="aaaaaaaa",
            )
        )
        release_gate.set()
        deadline = time.monotonic() + 30
        while len(handled) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert handled == ["first", "second"]
    finally:
        release_gate.set()
        queue.shutdown()
