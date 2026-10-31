from time import sleep
from unittest.mock import Mock

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
    create_task_queue()
    sleep(2.0)
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
    class BusyQueue(BaseQueue):
        def handle_block(self, _context):
            sleep(2.0)
            return "late result"

    queue = BusyQueue()
    try:
        mocker.patch("seagoat.queue.base_queue.TASK_TIMEOUT_SECONDS", 0.1)
        with pytest.raises(TaskTimedOut):
            queue.enqueue("block")
    finally:
        queue.shutdown()


def test_late_result_from_timed_out_task_is_dropped(mocker):
    class BusyQueue(BaseQueue):
        def handle_block(self, _context):
            sleep(2.0)
            return "late result"

        def handle_echo(self, _context, value):
            return value

    queue = BusyQueue()
    try:
        mocker.patch("seagoat.queue.base_queue.TASK_TIMEOUT_SECONDS", 0.1)
        with pytest.raises(TaskTimedOut):
            queue.enqueue("block")

        # Let the blocked handler finish and drop its result, then make sure
        # a later caller gets its own result, not the stale one.
        sleep(2.2)
        assert queue.enqueue("echo", "fresh result") == "fresh result"
    finally:
        queue.shutdown()
