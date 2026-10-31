import threading
import time
from unittest.mock import Mock, patch

import pytest

from seagoat.queue.base_queue import BaseQueue, TaskFailed, TaskTimedOut
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
