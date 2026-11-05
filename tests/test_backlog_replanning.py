"""Repository edits are replanned while an indexing backlog is outstanding.

Drives TaskQueue maintenance by hand against a real local Chroma with a
deterministic fake embedding function and a thread-less scheduler, with a
fake clock for the maintenance interval.
"""

import threading

import pytest

from seagoat.queue.task_queue import SECONDS_BETWEEN_MAINTENANCE
from tests.fixtures.scheduling import drive
from tests.test_index_pruning import _collection_ids, _make_engine, _make_task_queue


@pytest.fixture(name="backlog")
def backlog_fixture(repo, mocker):
    """A project with its whole repository planned in one-chunk batches."""
    clock = {"now": 1000.0}
    mocker.patch(
        "seagoat.queue.task_queue.time.monotonic", side_effect=lambda: clock["now"]
    )
    engine, _ = _make_engine(repo.working_dir)
    engine.config["server"]["chroma"]["batchSize"] = 1
    queue, context = _make_task_queue(engine)
    written = []
    real_write = context["lane"].write

    def recording_write(batch):
        real_write(batch)
        written.extend(batch.ids)

    context["lane"].write = recording_write

    def next_pass():
        clock["now"] += SECONDS_BETWEEN_MAINTENANCE + 1
        queue.handle_maintenance(context)

    queue.handle_maintenance(context)
    assert len(context["lane"].heap) > 3, "the test repo should give a backlog"
    return queue, context, written, next_pass


def _queued(context):
    return [batch for _, _, batch in context["lane"].heap]


def _queued_ids(context):
    return {i for batch in _queued(context) for i in batch.ids}


def _path_of_last_queued_file(context):
    last = max(_queued(context), key=lambda batch: batch.sort_key)
    return last.metadatas[0]["path"]


def test_edit_during_backlog_is_indexed_and_replaced_batches_never_run(repo, backlog):
    queue, context, written, next_pass = backlog
    scheduler = context["scheduler"]
    assert scheduler.run_once()
    edited = _path_of_last_queued_file(context)
    old_queued = _queued_ids(context)
    generation = context["lane"].plan_generation()

    repo.add_file_change_commit(edited, "a brand new edited body\n", "Edit")
    next_pass()

    assert context["lane"].plan_generation() == generation + 1
    new_queued = _queued_ids(context)
    replaced = old_queued - new_queued
    assert replaced, "the old version of the edited file must leave the queue"
    added = new_queued - old_queued
    assert added, "the new version of the edited file must be queued"

    drive(queue, context)

    assert added <= set(written)
    assert not replaced & set(written)
    assert context["lane"].outstanding() == 0
    assert context["seagoat_engine"].get_indexing_stats()["pending"] == 0


def test_unchanged_repository_during_backlog_does_not_replan(backlog, mocker):
    _, context, _, next_pass = backlog
    assert context["scheduler"].run_once()
    queued = [batch.seq for batch in _queued(context)]
    generation = context["lane"].plan_generation()
    plan = mocker.spy(context["seagoat_engine"], "plan_indexing")

    next_pass()

    plan.assert_not_called()
    assert context["lane"].plan_generation() == generation
    assert [batch.seq for batch in _queued(context)] == queued


def test_quarantined_chunks_stay_out_of_the_new_plan(repo, backlog):
    _, context, _, next_pass = backlog
    quarantined = min(_queued_ids(context))
    context["failed_chunks"].add(quarantined)

    repo.add_file_change_commit("unrelated.txt", "something new\n", "Add a file")
    next_pass()

    assert quarantined not in _queued_ids(context)


def test_row_written_by_an_old_plan_is_pruned_after_the_backlog(repo, backlog):
    queue, context, written, next_pass = backlog
    lane = context["lane"]
    scheduler = context["scheduler"]
    first = min(_queued(context), key=lambda batch: batch.sort_key)
    stale_id = first.ids[0]
    edited = first.metadatas[0]["path"]

    entered, release = threading.Event(), threading.Event()
    recording_write = lane.write

    def blocking_write(batch):
        if batch.ids == first.ids:
            entered.set()
            assert release.wait(30)
        recording_write(batch)

    lane.write = blocking_write
    runner = threading.Thread(target=scheduler.run_once, daemon=True)
    runner.start()
    try:
        assert entered.wait(30)
        # The running batch's file is edited: its row will be stale
        repo.add_file_change_commit(edited, "the running file, edited\n", "Edit")
        next_pass()
    finally:
        release.set()
        runner.join(30)
    assert not runner.is_alive()
    assert stale_id in written

    # Completing the old-generation batch asks for one pass after the
    # backlog, not for a replan now (which would make the next running batch
    # old too, and replan again on every completion)
    task = queue._task_queue.get_nowait()
    queue._handle_task(context, task)
    assert context["replan_after_drain"] is True
    assert context["replan_pending"] is False
    assert lane.outstanding() > 0
    plan_calls = []
    real_plan = context["seagoat_engine"].plan_indexing
    context["seagoat_engine"].plan_indexing = lambda **kw: (
        plan_calls.append(1) or real_plan(**kw)
    )
    next_pass()
    assert plan_calls == []
    assert not queue._has_pending_task(queue.PRUNE_TASK)

    drive(queue, context)
    assert lane.outstanding() == 0
    assert stale_id in _collection_ids(repo.working_dir)

    # The pass after the backlog finds the stale row and prunes it
    next_pass()
    assert plan_calls == [1]
    drive(queue, context)
    assert stale_id not in _collection_ids(repo.working_dir)
    assert context["replan_after_drain"] is False
