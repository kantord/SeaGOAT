from unittest.mock import Mock

import pytest

from seagoat.queue import TaskQueue


@pytest.fixture(name="task_queue")
def task_queue_(repo):
    return TaskQueue(repo_path=repo.working_dir)


@pytest.mark.parametrize(
    "chunks_analyzed, unanalyzed, expected_accuracy",
    [
        (0, 0, 100),
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
def test_handle_get_stats(task_queue, chunks_analyzed, unanalyzed, expected_accuracy):
    context = {
        "seagoat_engine": Mock(),
        "chunks_to_analyze": Mock(),
    }

    context["seagoat_engine"].cache.data = {
        "chunks_already_analyzed": [None] * chunks_analyzed
    }
    context["chunks_to_analyze"].qsize.return_value = unanalyzed

    stats = task_queue.handle_get_stats(context)
    task_queue.shutdown()

    assert stats["accuracy"]["percentage"] == expected_accuracy
