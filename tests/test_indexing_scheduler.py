"""Tests for the process-wide indexing scheduler.

Most tests step a thread-less scheduler with a fake monotonic clock, so the
order of execution is fully deterministic. Tests that need real concurrency
(cancellation of a running batch, dependency cycles, no polling) use explicit
events and bounded joins instead of sleeps.
"""

import threading
import time
from queue import PriorityQueue
from unittest.mock import Mock

import pytest

from seagoat.engine import RepositoryChanged
from seagoat.projects import Projects
from seagoat.queue.base_queue import HIGH_PRIORITY
from seagoat.queue.indexing_scheduler import (
    BatchCompleted,
    DocumentFailed,
    IndexBatch,
    IndexingScheduler,
    ResourceRecovered,
)
from seagoat.queue.task_queue import TaskQueue
from seagoat.sources.chroma import EmbeddingError
from seagoat.utils.wait import wait_for
from tests.fixtures.scheduling import FakeClock, drive, manual_scheduler
from tests.fixtures.sources import mock_sources_context


class Project:
    """A scripted project: records writes, probes and delivered events."""

    def __init__(self, scheduler, name, resource="model", clock=None):
        self.name = name
        self.writes: list[tuple[str, ...]] = []
        self.threads: set[str] = set()
        self.probes = 0
        self.events: list = []
        self.poison: set[str] = set()
        self.embedding_down = False
        self.storage_down = False
        self.lane = scheduler.register(
            name,
            resource,
            write=self._write,
            probe=self._probe,
            deliver=self.events.append,
        )

    def _write(self, batch):
        self.threads.add(threading.current_thread().name)
        if self.embedding_down or (self.poison & set(batch.ids)):
            raise EmbeddingError("cannot embed")
        if self.storage_down:
            raise OSError("storage down")
        self.writes.append(batch.ids)

    def _probe(self):
        self.probes += 1
        if self.embedding_down:
            raise EmbeddingError("model down")

    def submit(self, *ranks, size=1):
        batches = []
        for index, rank in enumerate(ranks):
            ids = tuple(f"{self.name}-{rank}-{index}-{n}" for n in range(size))
            batches.append(
                IndexBatch(
                    self.name,
                    0,
                    None,
                    ids,
                    tuple(f"text {i}" for i in ids),
                    tuple({} for _ in ids),
                    rank=rank,
                )
            )
        self.lane.submit(batches)

    def completed(self, kind: type = BatchCompleted):
        return [event for event in self.events if isinstance(event, kind)]

    def ack_all(self):
        for event in list(self.events):
            if isinstance(event, (BatchCompleted, DocumentFailed)):
                self.lane.ack(event.batch)
        self.events.clear()


def _run_order(scheduler, projects):
    """Run to idle; return the (project, rank) sequence of executed batches."""
    order = []
    for project in projects:
        original = project._write

        def recording(batch, original=original):
            original(batch)
            order.append((batch.project_id, batch.rank))

        project.lane.write = recording
    scheduler.run_until_idle()
    return order


# -- ordering and fairness ---------------------------------------------------


def test_batches_of_all_projects_run_by_absolute_file_rank():
    scheduler = manual_scheduler(fairness_burst=100)
    a = Project(scheduler, "a")
    b = Project(scheduler, "b")
    a.submit(0, 5, 9)
    b.submit(1, 2, 7)

    assert _run_order(scheduler, [a, b]) == [
        ("a", 0),
        ("b", 1),
        ("b", 2),
        ("a", 5),
        ("b", 7),
        ("a", 9),
    ]


def test_equal_ranks_are_served_first_in_first_out_across_and_within_projects():
    scheduler = manual_scheduler(fairness_burst=100)
    a = Project(scheduler, "a")
    b = Project(scheduler, "b")
    b.submit(3)
    a.submit(3, 3)
    b.submit(3)

    order = _run_order(scheduler, [a, b])

    assert order == [("b", 3), ("a", 3), ("a", 3), ("b", 3)]
    # within a project the same rank keeps submission order
    assert a.writes == sorted(a.writes, key=lambda ids: int(ids[0].split("-")[2]))


def test_fairness_prevents_a_busy_project_from_starving_another():
    burst = 3
    scheduler = manual_scheduler(fairness_burst=burst)
    busy = Project(scheduler, "busy")
    quiet = Project(scheduler, "quiet")
    busy.submit(*([0] * 20))  # all more important than the quiet project's work
    quiet.submit(500, 501)

    order = [project for project, _ in _run_order(scheduler, [busy, quiet])]

    # The quiet project is never kept waiting for more than `burst` batches,
    # and again gets its turn after the next burst of the busy project
    assert [i for i, project in enumerate(order) if project == "quiet"] == [
        burst,
        2 * burst + 1,
    ]
    assert order.count("busy") == 20 and order.count("quiet") == 2


def test_fairness_rotates_through_every_waiting_project():
    # 2026-11-06 review: on a forced yield the best-ranked other project ran,
    # and the top project came straight back, so a third project first ran at
    # batch 28 of 60
    burst = 4
    scheduler = manual_scheduler(fairness_burst=burst)
    projects = [Project(scheduler, name) for name in "abc"]
    for offset, project in zip((0, 1000, 2000), projects):
        project.submit(*range(offset, offset + 20))

    order = "".join(project for project, _ in _run_order(scheduler, projects))

    assert order.startswith("aaaabcaaaabc"), order
    # The documented bound: while a project has work, it waits for at most
    # `burst` batches of each other project in a row
    for waiting in "abc":
        for other in "abc".replace(waiting, ""):
            while_waiting = order[: order.rfind(waiting)]
            for run in while_waiting.split(waiting):
                assert run.count(other) <= burst, (waiting, other, order)


def _last_served(scheduler):
    lane = max(scheduler._lanes, key=lambda lane: lane.last_served)
    assert lane.recent, "the scheduler has not served any lane yet"
    return lane.project_id


def test_a_project_that_keeps_replanning_important_files_cannot_starve_others():
    scheduler = manual_scheduler(fairness_burst=2)
    busy = Project(scheduler, "busy")
    other = Project(scheduler, "other")
    other.submit(1000)

    served = []
    for _ in range(3):
        busy.submit(0)  # always more important than anything of `other`
        scheduler.run_once()
        served.append(_last_served(scheduler))
        busy.submit(0)
        scheduler.run_once()
        served.append(_last_served(scheduler))

    assert "other" in served[:3]


def test_fairness_does_not_idle_the_scheduler_when_only_one_project_has_work():
    scheduler = manual_scheduler(fairness_burst=1)
    only = Project(scheduler, "only")
    only.submit(0, 1, 2, 3, 4)

    assert scheduler.run_until_idle() == 5


# -- shared and independent resources ---------------------------------------


def test_projects_sharing_a_resource_back_off_together_and_probe_once():
    clock = FakeClock()
    scheduler = manual_scheduler(clock)
    a = Project(scheduler, "a", resource="shared")
    b = Project(scheduler, "b", resource="shared")
    a.embedding_down = b.embedding_down = True
    a.submit(0, 2)
    b.submit(1, 3)

    scheduler.run_until_idle()

    # One failed write and one probe for the whole resource: b never touched
    # the broken model, and a's second batch did not retry
    assert a.probes + b.probes == 1
    assert scheduler.resource_status("shared")["down"] is True
    assert a.lane.status()["pause_reason"] == "embedding"
    assert b.lane.status()["pause_reason"] == "embedding"
    assert a.lane.status()["queued"] == 2 and b.lane.status()["queued"] == 2
    assert a.completed() == [] and b.completed() == []

    # Nothing happens before the shared retry deadline, however often we step
    clock.advance(9.9)
    assert scheduler.run_until_idle() == 0
    assert a.probes + b.probes == 1

    # At the deadline a single probe runs for both projects; still down
    clock.advance(0.2)
    scheduler.run_until_idle()
    assert a.probes + b.probes == 2

    # Recovery: one probe, both projects are told, all work completes
    a.embedding_down = b.embedding_down = False
    clock.advance(10)
    scheduler.run_until_idle()
    assert a.probes + b.probes == 3
    assert scheduler.resource_status("shared")["down"] is False
    assert len(a.completed(ResourceRecovered)) == 1
    assert len(b.completed(ResourceRecovered)) == 1
    assert len(a.completed()) == 2 and len(b.completed()) == 2


def test_projects_on_different_resources_are_independent():
    clock = FakeClock()
    scheduler = manual_scheduler(clock)
    broken = Project(scheduler, "broken", resource="model-1")
    healthy = Project(scheduler, "healthy", resource="model-2")
    broken.embedding_down = True
    broken.submit(0, 1)
    healthy.submit(2, 3)

    scheduler.run_until_idle()

    assert scheduler.resource_status("model-1")["down"] is True
    assert scheduler.resource_status("model-2")["down"] is False
    assert len(healthy.completed()) == 2
    assert healthy.lane.status()["paused"] is False
    assert broken.lane.status()["paused"] is True
    assert broken.completed() == []


# -- failure classification --------------------------------------------------


def test_storage_failure_pauses_only_that_project_and_is_not_a_model_outage():
    clock = FakeClock()
    scheduler = manual_scheduler(clock)
    shared = "model"
    a = Project(scheduler, "a", resource=shared)
    b = Project(scheduler, "b", resource=shared)
    a.storage_down = True
    a.submit(0)
    b.submit(1, 2)

    scheduler.run_until_idle()

    status = a.lane.status()
    assert status["paused"] and status["pause_reason"] == "storage"
    assert status["queued"] == 1  # whole batch retained, not bisected
    assert a.probes == 0  # storage failures never probe the model
    assert scheduler.resource_status(shared)["down"] is False
    assert len(b.completed()) == 2  # the other project was not held back
    assert b.lane.status()["paused"] is False

    # Retried only after the deadline, then recovers without quarantine
    a.storage_down = False
    clock.advance(5)
    assert scheduler.run_until_idle() == 0
    clock.advance(5)
    scheduler.run_until_idle()
    assert len(a.completed()) == 1
    assert a.completed(DocumentFailed) == []
    assert a.lane.status()["paused"] is False


def test_poison_document_is_isolated_with_bounded_attempts():
    scheduler = manual_scheduler()
    project = Project(scheduler, "p")
    project.poison = {"p-0-0-5"}
    project.submit(0, size=8)

    scheduler.run_until_idle()

    failed = project.completed(DocumentFailed)
    assert [event.batch.ids for event in failed] == [("p-0-0-5",)]
    done = {i for event in project.completed() for i in event.batch.ids}
    assert done == {f"p-0-0-{n}" for n in range(8)} - {"p-0-0-5"}
    # bisection: at most 2 * log2(8) + 1 failing attempts, none per document
    assert project.probes <= 7
    assert project.lane.outstanding() == len(project.events)  # all await the ack
    assert scheduler.resource_status("model")["down"] is False


# -- accounting and completion ----------------------------------------------


def test_completion_is_published_after_upsert_and_acknowledged_by_the_project():
    scheduler = manual_scheduler()
    project = Project(scheduler, "p")
    project.submit(0, 1)
    seen_at_write = []
    original = project._write

    def write(batch):
        seen_at_write.append(list(project.events))
        original(batch)

    project.lane.write = write

    assert project.lane.status()["queued"] == 2
    scheduler.run_once()

    # Nothing was published while the write ran; one event afterwards
    assert seen_at_write == [[]]
    assert len(project.completed()) == 1
    status = project.lane.status()
    assert (status["queued"], status["in_flight"], status["awaiting_completion"]) == (
        1,
        0,
        1,
    )
    # still outstanding until the project acks: it may not replan/prune yet
    assert project.lane.outstanding() == 2

    scheduler.run_once()
    project.ack_all()
    assert project.lane.outstanding() == 0
    assert project.lane.status()["awaiting_completion"] == 0


def test_a_failed_write_publishes_no_completion():
    scheduler = manual_scheduler()
    project = Project(scheduler, "p")
    project.storage_down = True
    project.submit(0)

    scheduler.run_once()

    assert project.events == []
    assert project.lane.outstanding() == 1


def test_in_flight_work_is_counted():
    scheduler = IndexingScheduler()
    entered, release = threading.Event(), threading.Event()

    def write(_batch):
        entered.set()
        release.wait(10)

    lane = scheduler.register(
        "p",
        "model",
        write=write,
        probe=lambda: None,
        deliver=lambda event: None,
    )
    try:
        lane.submit([IndexBatch("p", 0, None, ("a",), ("t",), ({},), rank=0)])
        assert entered.wait(5)
        status = lane.status()
        assert (status["queued"], status["in_flight"]) == (0, 1)
        assert lane.outstanding() == 1
    finally:
        release.set()
        lane.unregister()
        scheduler.shutdown()


# -- cancellation / removal ---------------------------------------------------


def test_unregister_cancels_queued_work_and_stops_delivery():
    scheduler = manual_scheduler()
    gone = Project(scheduler, "gone")
    stays = Project(scheduler, "stays")
    gone.submit(0, 1, 2)
    stays.submit(5)

    assert gone.lane.unregister() is True

    scheduler.run_until_idle()
    assert gone.writes == [] and gone.events == []
    assert gone.lane.outstanding() == 0
    assert len(stays.completed()) == 1
    # a removed project cannot be revived by submitting again
    gone.submit(0)
    assert scheduler.run_until_idle() == 0
    assert gone.writes == []


def test_unregister_waits_for_a_running_batch_and_drops_its_late_completion():
    scheduler = IndexingScheduler()
    entered, release = threading.Event(), threading.Event()
    delivered = []
    writes = []

    def write(batch):
        entered.set()
        assert release.wait(10)
        writes.append(batch.ids)

    lane = scheduler.register(
        "p", "model", write=write, probe=lambda: None, deliver=delivered.append
    )
    try:
        lane.submit(
            [
                IndexBatch("p", 0, None, ("a",), ("t",), ({},), rank=0),
                IndexBatch("p", 0, None, ("b",), ("t",), ({},), rank=1),
            ]
        )
        assert entered.wait(5)

        # The running upsert cannot be cancelled: removal reports it
        assert lane.unregister(wait=True, timeout=0.05) is False
        assert lane.is_closed()
        # ...and it still counts, so no prune runs while it writes
        assert lane.outstanding() == 1
        assert lane.status()["awaiting_completion"] == 0

        release.set()
        assert lane.unregister(wait=True, timeout=5) is True
        assert lane.outstanding() == 0
        assert lane.status()["awaiting_completion"] == 0
        # only the running batch ever wrote; the queued one was cancelled
        assert writes == [("a",)]
        # ...and its late completion never reached the removed project
        assert delivered == []
    finally:
        release.set()
        scheduler.shutdown()


def test_late_completion_event_cannot_revive_a_removed_task_queue():
    engine = Mock()
    scheduler = manual_scheduler()
    queue = TaskQueue.__new__(TaskQueue)
    queue.kwargs = {}
    queue._task_queue = PriorityQueue()
    lane = scheduler.register(
        "p",
        "model",
        write=engine.write_batch,
        probe=engine.probe_embedding,
        deliver=queue._deliver_index_event,
    )
    context = {"seagoat_engine": engine, "lane": lane, "scheduler": scheduler}
    queue._ensure_recovery_state(context)
    batch = IndexBatch("p", 1, "model", ("a",), ("t",), ({},), rank=0)

    lane.unregister()
    queue.handle_index_event(context, BatchCompleted(batch))

    engine.complete_batch.assert_not_called()
    assert context["paused"] is False and context["replan_pending"] is False


def test_projects_remove_stops_the_queue_and_cancels_its_work(repo):
    scheduler = IndexingScheduler(retry_seconds=60)
    with mock_sources_context(repo, {}, {}, embedding=_always_failing) as (_, _):
        projects = Projects(
            lambda path, config: TaskQueue(repo_path=path, scheduler=scheduler),
        )
        project = projects.get(repo.working_dir)
        try:
            # embedding is down: batches stay queued in the scheduler
            wait_for(
                lambda: project.queue.enqueue("get_stats")["indexing"]["paused"], 30
            )
            lane = project.queue._lane
            assert lane.outstanding() > 0

            assert projects.remove(repo.working_dir) is True

            assert lane.is_closed() and lane.outstanding() == 0
            assert projects.repo_paths() == []
            assert projects.remove(repo.working_dir) is False
        finally:
            scheduler.shutdown()


def _always_failing():
    raise EmbeddingError("model down")


# -- no dependency cycles / liveness -----------------------------------------


def test_scheduler_delivers_without_holding_its_lock_or_waiting_for_projects():
    scheduler = IndexingScheduler()
    probed = threading.Event()
    results = []

    def deliver(event):
        # If the scheduler held its lock here, this helper thread would block
        helper = threading.Thread(target=lambda: results.append(lane.outstanding()))
        helper.start()
        helper.join(5)
        results.append(not helper.is_alive())
        probed.set()

    lane = scheduler.register(
        "p", "model", write=lambda batch: None, probe=lambda: None, deliver=deliver
    )
    try:
        lane.submit([IndexBatch("p", 0, None, ("a",), ("t",), ({},), rank=0)])
        assert probed.wait(10)
        assert results == [1, True]
    finally:
        lane.unregister()
        scheduler.shutdown()


def test_a_blocked_project_queue_never_blocks_other_projects(repo):
    scheduler = IndexingScheduler()
    blocked_in_handler, release = threading.Event(), threading.Event()

    class BlockedQueue(TaskQueue):
        def handle_index_event(self, context, event):
            blocked_in_handler.set()
            assert release.wait(30)
            super().handle_index_event(context, event)

    with mock_sources_context(repo, {}, {}) as (_store, _):
        blocked = BlockedQueue(repo_path=repo.working_dir, scheduler=scheduler)
        other = Project(scheduler, "other", resource="another-model")
        try:
            assert blocked_in_handler.wait(30)
            # `blocked`'s worker is stuck. It still has queued completions
            # waiting for it; the scheduler must keep serving everyone else.
            for _ in range(5):
                other.submit(0)
            wait_for(lambda: len(other.completed()) == 5, 10)
        finally:
            release.set()
            blocked.shutdown()
            scheduler.shutdown()


def _stats(queue):
    stats = queue.enqueue("get_stats")
    assert stats is not None
    return stats


def test_queries_and_stats_stay_serviceable_while_indexing_is_paused(repo):
    scheduler = IndexingScheduler(retry_seconds=60)
    with mock_sources_context(
        repo, {"file1.md": [(1, 0.2)]}, {}, embedding=_always_failing
    ):
        queue = TaskQueue(repo_path=repo.working_dir, scheduler=scheduler)
        try:
            wait_for(lambda: _stats(queue)["indexing"]["paused"], 30)
            stats = _stats(queue)
            assert stats["indexing"]["pause_reason"] == "embedding"
            assert stats["indexing"]["queued"] > 0
            assert stats["chunks"]["unanalyzed"] > 0
            assert queue.enqueue(
                "query", query="x", limit_clue=10, context_above=0, context_below=0
            )
        finally:
            queue.shutdown()
            scheduler.shutdown()


# -- cleanup safety -------------------------------------------------------------


def test_prune_never_overlaps_outstanding_writes_and_runs_after_the_last_ack():
    log = []
    engine = Mock()
    engine.path = "p"
    engine.embedding_resource_key.return_value = "model"
    engine.config = {"server": {"chroma": {"batchSize": 2}}}
    engine.repository.get_status_hash.return_value = "h"
    chunks = [
        Mock(
            chunk_id=f"c{n}",
            chunk="t",
            path="f",
            codeline=n,
            object_id="o",
            file_rank=0,
        )
        for n in range(4)
    ]
    engine.plan_indexing.return_value = chunks
    engine.write_batch.side_effect = lambda batch: log.append("write")
    engine.prune_stale.side_effect = lambda limit: log.append("prune")
    engine.pending_prune_count.side_effect = lambda: (
        0 if "prune" in log or not engine.plan_indexing.called else 3
    )
    engine.get_indexing_stats.return_value = {
        "analyzed": 0,
        "pending": 0,
        "total": 0,
        "failed": 0,
    }

    queue = TaskQueue.__new__(TaskQueue)
    queue.kwargs = {}
    queue._task_queue = PriorityQueue()
    scheduler = manual_scheduler()
    lane = scheduler.register(
        "p",
        "model",
        write=engine.write_batch,
        probe=engine.probe_embedding,
        deliver=queue._deliver_index_event,
    )
    context = {
        "seagoat_engine": engine,
        "lane": lane,
        "scheduler": scheduler,
        "last_maintenance": None,
        "last_repo_state_hash": None,
    }
    queue._ensure_recovery_state(context)

    queue.handle_maintenance(context)  # plans and submits two batches
    assert lane.outstanding() == 2
    # no prune task was queued, and an explicit one is a no-op while jobs exist
    assert not queue._has_pending_task(queue.PRUNE_TASK)
    queue.handle_prune_index(context)
    engine.prune_stale.assert_not_called()
    # ordinary replanning is deferred as well
    context["last_maintenance"] = None
    queue.handle_maintenance(context)
    assert engine.plan_indexing.call_count == 1

    # first batch written and published, second still queued: still no prune
    scheduler.run_once()
    assert queue._task_queue.qsize() == 1
    drive_task = queue._task_queue.get_nowait()
    queue.handle_index_event(context, *drive_task.args)
    assert lane.outstanding() == 1
    assert not queue._has_pending_task(queue.PRUNE_TASK)

    drive(queue, context)

    assert log == ["write", "write", "prune"]
    assert lane.outstanding() == 0


# -- timing, threading and resource use --------------------------------------


def test_scheduler_blocks_without_polling_until_the_retry_deadline():
    scheduler = IndexingScheduler(retry_seconds=0.4)
    project = Project(scheduler, "p")
    project.embedding_down = True
    try:
        project.submit(0)
        wait_for(lambda: scheduler.resource_status("model")["down"], 10)
        time.sleep(0.9)
        # first failure probe + about two deadline probes: no busy loop
        assert 2 <= project.probes <= 4

        project.embedding_down = False
        wait_for(lambda: len(project.completed()) == 1, 10)
    finally:
        scheduler.shutdown()


def test_idle_scheduler_thread_sleeps_until_work_arrives():
    scheduler = IndexingScheduler()
    project = Project(scheduler, "p")
    try:
        time.sleep(0.2)
        assert project.writes == []
        project.submit(0)
        wait_for(lambda: len(project.completed()) == 1, 10)
    finally:
        scheduler.shutdown()


def test_all_projects_write_from_the_single_scheduler_thread():
    scheduler = IndexingScheduler()
    a = Project(scheduler, "a", resource="m1")
    b = Project(scheduler, "b", resource="m2")
    try:
        a.submit(0, 1, 2)
        b.submit(0, 1, 2)
        wait_for(lambda: len(a.completed()) == 3 and len(b.completed()) == 3, 10)
        assert a.threads == b.threads == {"indexing-scheduler"}
    finally:
        scheduler.shutdown()


def test_batches_are_self_contained_and_split_without_losing_documents():
    batch = IndexBatch(
        "p",
        1,
        "model",
        ("a", "b", "c"),
        ("ta", "tb", "tc"),
        ({"path": "a"}, {"path": "b"}, {"path": "c"}),
        rank=4,
        seq=7,
    )

    left, right = batch.halves()

    assert (left.ids, right.ids) == (("a",), ("b", "c"))
    assert (left.documents, right.documents) == (("ta",), ("tb", "tc"))
    assert right.metadatas == ({"path": "b"}, {"path": "c"})
    assert left.sort_key < right.sort_key
    assert left.rank == right.rank == 4 and left.seq == right.seq == 7
    assert left.key != right.key


def test_engine_write_batch_does_not_publish_progress(repo):
    with mock_sources_context(repo, {}, {}) as (chroma_source, _):
        from seagoat.engine import Engine

        engine = Engine(repo.working_dir)
        chunks = engine.plan_indexing()
        assert chunks
        pending = engine.get_indexing_stats()["pending"]
        batch = IndexBatch(
            "p",
            1,
            engine.embedding_resource_key(),
            tuple(chunk.chunk_id for chunk in chunks),
            tuple(chunk.chunk for chunk in chunks),
            tuple({} for _ in chunks),
            rank=0,
        )

        engine.write_batch(batch)

        # stored in Chroma, but counters belong to the project's own thread
        assert chroma_source["indexed_ids"](list(batch.ids)) == set(batch.ids)
        assert engine.get_indexing_stats()["pending"] == pending
        engine.complete_batch(batch.ids)
        assert engine.get_indexing_stats()["pending"] == 0


@pytest.mark.parametrize("burst", [1, 2, 5])
def test_fairness_bound_holds_for_any_burst(burst):
    scheduler = manual_scheduler(fairness_burst=burst)
    busy = Project(scheduler, "busy")
    quiet = Project(scheduler, "quiet")
    busy.submit(*([0] * 30))
    quiet.submit(999)

    order = [project for project, _ in _run_order(scheduler, [busy, quiet])]

    assert order.index("quiet") == burst


def test_default_priority_of_completion_events_is_high(repo):
    # Completion events are delivered at high priority so they are never
    # stuck behind low-priority cleanup in the project's queue
    queue = TaskQueue.__new__(TaskQueue)
    queue._task_queue = PriorityQueue()
    queue._deliver_index_event(ResourceRecovered())
    task = queue._task_queue.get_nowait()
    assert (task.name, task.priority) == ("index_event", HIGH_PRIORITY)


# -- replanning (Plan.replace) ----------------------------------------------


def test_replace_drops_queued_batches_keeps_running_batch_and_stays_exact():
    scheduler = manual_scheduler()
    entered, release = threading.Event(), threading.Event()
    writes = []

    def make_batch(rank):
        return IndexBatch(
            "p",
            0,
            None,
            (f"p-{rank}",),
            (f"text {rank}",),
            ({},),
            rank=rank,
        )

    def blocking_write(batch):
        writes.append(batch.ids)
        entered.set()
        assert release.wait(30)

    project = Project(scheduler, "p")
    project.lane.write = blocking_write
    project.lane.submit([make_batch(0), make_batch(1)])
    # The scheduler has no thread of its own: run the first batch on one so
    # it can block mid-write while the plan is replaced
    runner = threading.Thread(target=scheduler.run_once, daemon=True)
    runner.start()
    try:
        assert entered.wait(30)
        assert project.lane.in_flight.ids == ("p-0",)
        assert project.lane.outstanding() == 2
        assert project.lane.status() == {
            "queued": 1,
            "in_flight": 1,
            "awaiting_completion": 0,
            "paused": False,
            "pause_reason": None,
            "retry_after": None,
        }
        old_generation = project.lane.plan_generation()

        project.lane.replace([make_batch(5), make_batch(6)])

        # The queued old batch is gone (never acked, no longer outstanding),
        # the running batch is untouched, and the new batches carry the next
        # generation.
        assert project.lane.plan_generation() == old_generation + 1
        assert project.lane.in_flight is not None
        assert project.lane.in_flight.ids == ("p-0",)
        assert project.lane.in_flight.generation == old_generation
        assert [batch.ids for _, _, batch in project.lane.heap] == [
            ("p-5",),
            ("p-6",),
        ]
        assert {batch.generation for _, _, batch in project.lane.heap} == {
            old_generation + 1
        }
        assert project.lane.outstanding() == 3
        assert project.lane.status() == {
            "queued": 2,
            "in_flight": 1,
            "awaiting_completion": 0,
            "paused": False,
            "pause_reason": None,
            "retry_after": None,
        }
    finally:
        release.set()
        runner.join(30)
        scheduler.shutdown()

    # The running batch completed normally even though the plan was replaced
    assert not runner.is_alive()
    assert writes == [("p-0",)]
    assert [event.batch.ids for event in project.completed()] == [("p-0",)]


def test_replace_on_a_removed_lane_is_a_noop_and_does_not_revive_it():
    scheduler = manual_scheduler()
    project = Project(scheduler, "p")
    project.submit(0)
    assert project.lane.unregister() is True
    assert project.lane.is_closed()

    project.lane.replace(
        [
            IndexBatch(
                "p",
                0,
                None,
                ("p-late",),
                ("text",),
                ({},),
                rank=0,
            )
        ]
    )

    assert project.lane.is_closed()
    assert project.lane.outstanding() == 0
    assert project.lane.status()["queued"] == 0
    assert scheduler.run_until_idle() == 0
    assert project.completed() == []
    assert project.writes == []


def _prune_queue_and_context():
    """Scripted queue/context for direct handle_prune_index tests."""
    engine = Mock()
    engine.path = "p"
    engine.embedding_resource_key.return_value = "model"
    engine.config = {"server": {"chroma": {"batchSize": 2}}}
    engine.repository.get_status_hash.return_value = "h"

    queue = TaskQueue.__new__(TaskQueue)
    queue.kwargs = {}
    queue._task_queue = PriorityQueue()
    scheduler = manual_scheduler()
    lane = scheduler.register(
        "p",
        "model",
        write=engine.write_batch,
        probe=engine.probe_embedding,
        deliver=queue._deliver_index_event,
    )
    context = {
        "seagoat_engine": engine,
        "lane": lane,
        "scheduler": scheduler,
        "last_maintenance": None,
        "last_repo_state_hash": None,
    }
    queue._ensure_recovery_state(context)
    return queue, context, engine


def test_prune_repository_changed_does_not_pause_indexing():
    queue, context, engine = _prune_queue_and_context()
    engine.prune_stale.side_effect = RepositoryChanged(
        "repository changed since planning; refusing to prune stale rows"
    )

    queue.handle_prune_index(context)

    assert context["paused"] is False
    assert context["pause_reason"] is None
    assert context["replan_pending"] is True


def test_prune_storage_error_still_pauses_indexing():
    queue, context, engine = _prune_queue_and_context()
    engine.prune_stale.side_effect = OSError("storage down")

    queue.handle_prune_index(context)

    assert context["paused"] is True
    assert context["pause_reason"] == "storage"
    assert context["replan_pending"] is True


# -- stale batches of a replaced plan ---------------------------------------


def _make_new_batch(project, rank, size=1):
    """A batch that belongs to a fresh plan (its ids never collide with the
    batches the ``Project`` helper builds, whose ids look like ``p-0-0-...``)."""
    ids = tuple(f"{project.name}-new-{rank}-{n}" for n in range(size))
    return IndexBatch(
        project.name,
        0,
        None,
        ids,
        tuple(f"text {i}" for i in ids),
        tuple({} for _ in ids),
        rank=rank,
    )


def _fail_running_batch_after_replace(scheduler, project, fail, new_batches, size=1):
    """Step the scheduler on a thread so a batch is in flight, replace the
    plan while it runs, let the batch fail, and return the failed batch.

    The custom write fails only the in-flight batch; batches of the new plan
    go through the project's own ``_write`` (honoring its flags)."""
    entered, release = threading.Event(), threading.Event()
    original_write = project._write

    def write(batch):
        if entered.is_set():
            return original_write(batch)  # a batch of the new plan
        entered.set()
        assert release.wait(30)
        fail(batch)

    project.lane.write = write
    project.submit(0, size=size)
    runner = threading.Thread(target=scheduler.run_once, daemon=True)
    runner.start()
    try:
        assert entered.wait(30)
        project.lane.replace(new_batches)
        return project.lane.in_flight
    finally:
        release.set()
        runner.join(30)


def test_stale_storage_failure_pauses_lane_but_does_not_retry_old_plan():
    clock = FakeClock()
    scheduler = manual_scheduler(clock)
    project = Project(scheduler, "p")

    def fail(_batch):
        raise OSError("storage down")

    failed = _fail_running_batch_after_replace(
        scheduler, project, fail, [_make_new_batch(project, 5)]
    )
    assert failed.generation < project.lane.plan_generation()

    status = project.lane.status()
    assert status["paused"] and status["pause_reason"] == "storage"
    assert status["queued"] == 1  # only the new plan, not the failed batch
    assert project.lane.outstanding() == 1  # counts only the new plan
    assert project.writes == []  # old batch never ran again

    # The new plan is retried after the storage deadline, exactly once
    clock.advance(10)
    scheduler.run_until_idle()
    assert project.writes == [("p-new-5-0",)]
    project.ack_all()
    assert project.lane.outstanding() == 0


def test_stale_embedding_failure_with_many_ids_does_not_bisect_old_plan():
    scheduler = manual_scheduler()
    project = Project(scheduler, "p")

    def fail(_batch):
        raise EmbeddingError("poison document")

    failed = _fail_running_batch_after_replace(
        scheduler, project, fail, [_make_new_batch(project, 5)], size=8
    )
    assert failed.ids == tuple(f"p-0-0-{n}" for n in range(8))
    assert failed.generation < project.lane.plan_generation()

    # No halves of the stale batch were put back on the heap
    assert project.completed(DocumentFailed) == []
    assert project.lane.outstanding() == 1  # only the new plan
    assert [batch.ids for _, _, batch in project.lane.heap] == [("p-new-5-0",)]

    scheduler.run_until_idle()
    assert project.writes == [("p-new-5-0",)]


def test_stale_single_id_embedding_failure_quarantines_nothing():
    scheduler = manual_scheduler()
    project = Project(scheduler, "p")

    def fail(_batch):
        raise EmbeddingError("poison document")

    failed = _fail_running_batch_after_replace(
        scheduler, project, fail, [_make_new_batch(project, 5)]
    )
    assert failed.generation < project.lane.plan_generation()

    assert project.completed(DocumentFailed) == []
    assert project.lane.outstanding() == 1  # only the new plan
    scheduler.run_until_idle()
    assert project.writes == [("p-new-5-0",)]


def test_stale_model_down_does_not_retry_old_plan_after_recovery():
    clock = FakeClock()
    scheduler = manual_scheduler(clock)
    project = Project(scheduler, "p")
    project.embedding_down = True  # the probe after the write fails too

    def fail(_batch):
        raise EmbeddingError("model down")

    failed = _fail_running_batch_after_replace(
        scheduler, project, fail, [_make_new_batch(project, 5)]
    )
    assert failed.generation < project.lane.plan_generation()

    # The shared resource is still marked down and the lane still waits on it
    assert scheduler.resource_status("model")["down"] is True
    assert project.lane.status()["pause_reason"] == "embedding"
    # ...but the stale batch is gone; only the new plan is queued behind it
    assert project.lane.outstanding() == 1
    assert [batch.ids for _, _, batch in project.lane.heap] == [("p-new-5-0",)]

    # After recovery the new plan runs and the old batch never does
    project.embedding_down = False
    clock.advance(10)
    scheduler.run_until_idle()
    assert scheduler.resource_status("model")["down"] is False
    assert project.writes == [("p-new-5-0",)]


def test_replace_with_empty_plan_then_failure_leaves_nothing_outstanding():
    scheduler = manual_scheduler()
    project = Project(scheduler, "p")

    def fail(_batch):
        raise EmbeddingError("poison document")

    _fail_running_batch_after_replace(scheduler, project, fail, [])
    assert project.lane.outstanding() == 0
    assert project.lane.status()["queued"] == 0
    assert project.completed(DocumentFailed) == []
    assert scheduler.run_until_idle() == 0
    assert project.writes == []


def test_current_generation_batch_still_bisects_and_retries():
    clock = FakeClock()
    scheduler = manual_scheduler(clock)
    project = Project(scheduler, "p")

    # A batch of the current generation is still bisected around a poison id
    project.poison = {"p-new-0-3"}
    project.lane.replace([_make_new_batch(project, 0, size=8)])
    scheduler.run_until_idle()
    failed = project.completed(DocumentFailed)
    assert [event.batch.ids for event in failed] == [("p-new-0-3",)]
    done = {i for event in project.completed() for i in event.batch.ids}
    assert done == {f"p-new-0-{n}" for n in range(8)} - {"p-new-0-3"}
    assert scheduler.resource_status("model")["down"] is False
    project.ack_all()

    # A batch of the current generation is still retried after a storage hit
    project.storage_down = True
    project.lane.replace([_make_new_batch(project, 1)])
    scheduler.run_once()
    status = project.lane.status()
    assert status["paused"] and status["pause_reason"] == "storage"
    assert status["queued"] == 1 and project.lane.outstanding() == 1
    project.storage_down = False
    clock.advance(10)
    scheduler.run_until_idle()
    assert project.writes.count(("p-new-1-0",)) == 1  # written on the retry
    project.ack_all()
    assert project.lane.outstanding() == 0


def test_stale_storage_failure_with_no_work_left_does_not_stay_paused():
    # Only a successful batch clears a storage pause, and none is coming
    clock = FakeClock()
    scheduler = manual_scheduler(clock)
    project = Project(scheduler, "p")

    def fail(_batch):
        raise OSError("storage down")

    _fail_running_batch_after_replace(scheduler, project, fail, [])

    clock.advance(10)
    assert scheduler.run_until_idle() == 0
    status = project.lane.status()
    assert not status["paused"] and status["pause_reason"] is None


def test_stale_model_down_with_no_work_left_does_not_stay_down():
    # Probes only run for lanes with queued work, and none is coming
    scheduler = manual_scheduler()
    project = Project(scheduler, "p")
    project.embedding_down = True

    def fail(_batch):
        raise EmbeddingError("model down")

    _fail_running_batch_after_replace(scheduler, project, fail, [])

    assert scheduler.resource_status("model")["down"] is False
    assert not project.lane.status()["paused"]


def test_an_empty_plan_after_a_storage_failure_does_not_stay_paused():
    # The failed batch was current, so the lane paused. The next plan has
    # nothing to write, and only a successful batch clears a storage pause
    clock = FakeClock()
    scheduler = manual_scheduler(clock)
    project = Project(scheduler, "p")
    project.storage_down = True
    project.submit(0)
    scheduler.run_until_idle()
    assert project.lane.status()["pause_reason"] == "storage"

    project.lane.replace([])

    status = project.lane.status()
    assert not status["paused"] and status["pause_reason"] is None
    assert project.lane.outstanding() == 0


def test_an_empty_plan_after_a_model_outage_does_not_stay_held():
    # Probes only run for lanes with queued work, so after an empty plan no
    # probe would ever clear the hold
    clock = FakeClock()
    scheduler = manual_scheduler(clock)
    project = Project(scheduler, "p")
    project.embedding_down = True
    project.submit(0)
    scheduler.run_until_idle()
    assert project.lane.status()["pause_reason"] == "embedding"

    project.lane.replace([])

    status = project.lane.status()
    assert not status["paused"] and status["pause_reason"] is None
    assert project.lane.outstanding() == 0

    # The next plan probes the model before it writes anything
    probes_before = project.probes
    project.embedding_down = False
    project.submit(1)
    clock.advance(10)
    scheduler.run_until_idle()
    assert project.probes == probes_before + 1
    assert project.writes == [("p-1-0-0",)]
