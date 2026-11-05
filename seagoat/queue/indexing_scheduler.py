"""Process-wide scheduler for indexing batches.

One thread embeds and upserts batches for every project, so the shared
embedding model is used by one indexer at a time and the most important files
of *all* projects are indexed first.

Contracts
---------

Resource keys
    A batch's resource key identifies the embedding function it needs (see
    ``seagoat.sources.chroma.embedding_resource_key``). Outage, probe and retry
    state is owned per resource key, so projects that share a model back off
    together and are probed once, while projects with different models are
    independent. Storage failures belong to the project's own Chroma
    collection and pause only that project.

Scheduling policy
    Among eligible work the batch with the lowest ``(rank, seq)`` runs next:
    ``rank`` is the absolute position of the batch's best file in its project
    (0 is the top file), ``seq`` is a process-wide FIFO counter. Fairness: a
    project that has run ``FAIRNESS_BURST`` batches since another eligible
    project last ran yields to the eligible project that has waited longest. A project with eligible
    work therefore waits for at most ``FAIRNESS_BURST`` batches of each other
    busy project.

Completion protocol
    The scheduler never touches project state. After a successful upsert it
    delivers a ``BatchCompleted`` event to the project (a non-blocking
    enqueue); the project's own worker publishes the progress and then calls
    ``ProjectLane.ack``. A batch counts as outstanding until it is acked, so a
    project can tell when no job can still write (``outstanding() == 0``)
    before it replans or prunes.

Cancellation
    ``ProjectLane.unregister`` drops all queued batches, never revives the
    project and, with ``wait=True``, returns only once an already running
    batch has finished. Late results of such a batch are discarded.

No dependency cycles
    The scheduler thread never waits for a project queue: events are delivered
    with a non-blocking enqueue, outside the scheduler lock. Projects only
    take the scheduler lock for short, non-blocking calls.
"""

import heapq
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import count
from typing import Any

from seagoat.sources.chroma import EmbeddingError

logger = logging.getLogger(__name__)

# How long a resource (after a failed probe) or a project (after a storage
# failure) waits before it is tried again
RETRY_DEADLINE_SECONDS = 10

# How many batches in a row one project may be served while another project
# has eligible work
FAIRNESS_BURST = 4


@dataclass(frozen=True)
class IndexBatch:
    """A self-contained unit of indexing work.

    Everything needed to embed and store it is in the payload: the scheduler
    never reads project metadata or repository state.
    """

    project_id: str
    registration_id: int
    resource_key: Any
    ids: tuple[str, ...]
    documents: tuple[str, ...]
    metadatas: tuple[Mapping[str, Any], ...]
    rank: int
    seq: int = -1
    split: tuple[int, ...] = ()
    generation: int = 0

    @property
    def key(self) -> tuple[int, tuple[int, ...]]:
        """Unique identity of the batch within its project registration."""
        return (self.seq, self.split)

    @property
    def sort_key(self):
        return (self.rank, self.seq, self.split)

    def halves(self) -> tuple["IndexBatch", "IndexBatch"]:
        middle = len(self.ids) // 2

        def part(start, end, side):
            return replace(
                self,
                ids=self.ids[start:end],
                documents=self.documents[start:end],
                metadatas=self.metadatas[start:end],
                split=self.split + (side,),
            )

        return part(0, middle, 0), part(middle, None, 1)


def make_batches(
    project_id: str,
    registration_id: int,
    resource_key: Any,
    chunks: Sequence[Any],
    batch_size: int,
    metadata_of: Callable[[Any], Mapping[str, Any]],
) -> list[IndexBatch]:
    """Cut planned chunks (best file first) into self-contained batches."""
    batches = []
    for start in range(0, len(chunks), batch_size):
        part = chunks[start : start + batch_size]
        batches.append(
            IndexBatch(
                project_id=project_id,
                registration_id=registration_id,
                resource_key=resource_key,
                ids=tuple(chunk.chunk_id for chunk in part),
                documents=tuple(chunk.chunk for chunk in part),
                metadatas=tuple(dict(metadata_of(chunk)) for chunk in part),
                rank=min(getattr(chunk, "file_rank", 0) for chunk in part),
            )
        )
    return batches


@dataclass(frozen=True)
class BatchCompleted:
    """The batch was upserted. The project publishes progress, then acks."""

    batch: IndexBatch


@dataclass(frozen=True)
class DocumentFailed:
    """A single document cannot be embedded although the model works."""

    batch: IndexBatch


@dataclass(frozen=True)
class ResourceRecovered:
    """The shared embedding resource works again after an outage."""


class _Resource:
    def __init__(self, key):
        self.key = key
        self.down = False
        self.retry_after = 0.0
        # Lanes that had work held back by the outage
        self.held: set[ProjectLane] = set()
        self.probes = 0


class ProjectLane:
    """A project's handle on the scheduler (also its cancellation token)."""

    def __init__(
        self,
        scheduler: "IndexingScheduler",
        project_id: str,
        registration_id: int,
        resource: _Resource,
        write: Callable[[IndexBatch], None],
        probe: Callable[[], None],
        deliver: Callable[[Any], None],
    ):
        self._scheduler = scheduler
        self.project_id = project_id
        self.registration_id = registration_id
        self.resource = resource
        self.write = write
        self.probe = probe
        self.deliver = deliver
        # Everything below is guarded by the scheduler lock
        self.heap: list[tuple[Any, int, IndexBatch]] = []
        self.in_flight: IndexBatch | None = None
        self.outstanding_keys: set[Any] = set()
        self.paused_until: float | None = None
        self.pause_reason: str | None = None
        self.closed = False
        self.cancelled = 0
        self.generation = 0
        # Fairness bookkeeping, in the scheduler's service ticks: when this
        # lane last ran a batch (0 = never), and its last FAIRNESS_BURST runs
        self.last_served = 0
        self.recent: deque[int] = deque()

    @property
    def resource_key(self):
        return self.resource.key

    def submit(self, batches: Sequence[IndexBatch]) -> None:
        self._scheduler._submit(self, batches)

    def replace(self, batches: Sequence[IndexBatch]) -> None:
        """Atomically drop this lane's queued (not-yet-started) batches and
        queue ``batches`` as the current plan."""
        self._scheduler._replace(self, batches)

    def plan_generation(self) -> int:
        """The current plan generation; completed batches of an older
        generation are stale in the newer plan."""
        return self.generation

    def ack(self, batch: IndexBatch) -> None:
        self._scheduler._ack(self, batch)

    def outstanding(self) -> int:
        """Batches submitted but not yet acknowledged (queued, running, or
        waiting for the project to publish their result)."""
        return self._scheduler._outstanding(self)

    def is_closed(self) -> bool:
        return self.closed

    def status(self) -> dict[str, Any]:
        return self._scheduler._status(self)

    def unregister(self, wait: bool = True, timeout: float | None = None) -> bool:
        return self._scheduler._unregister(self, wait, timeout)


class IndexingScheduler:
    _shared: "IndexingScheduler | None" = None
    _shared_lock = threading.Lock()

    @classmethod
    def shared(cls) -> "IndexingScheduler":
        """The process-wide scheduler, started on first use."""
        with cls._shared_lock:
            if cls._shared is None:
                cls._shared = cls()
            return cls._shared

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        start: bool = True,
        fairness_burst: int | None = None,
        retry_seconds: float | None = None,
    ):
        self._clock = clock
        self._cond = threading.Condition()
        self._lanes: list[ProjectLane] = []
        self._resources: dict[Any, _Resource] = {}
        self._seq = count()
        self._registrations = count(1)
        self._stopped = False
        self._last_lane: ProjectLane | None = None
        self._ticks = count(1)
        self._fairness_burst = (
            FAIRNESS_BURST if fairness_burst is None else fairness_burst
        )
        self._retry_seconds = (
            RETRY_DEADLINE_SECONDS if retry_seconds is None else retry_seconds
        )
        self._thread: threading.Thread | None = None
        if start:
            # A daemon thread does not keep the process alive on its own
            self._thread = threading.Thread(
                target=self._run, name="indexing-scheduler", daemon=True
            )
            self._thread.start()

    # -- project-facing API -------------------------------------------------

    def register(
        self,
        project_id: str,
        resource_key: Any,
        write: Callable[[IndexBatch], None],
        probe: Callable[[], None],
        deliver: Callable[[Any], None],
    ) -> ProjectLane:
        with self._cond:
            resource = self._resources.setdefault(resource_key, _Resource(resource_key))
            lane = ProjectLane(
                self,
                project_id,
                next(self._registrations),
                resource,
                write,
                probe,
                deliver,
            )
            self._lanes.append(lane)
            return lane

    def resource_status(self, resource_key: Any) -> dict[str, Any]:
        with self._cond:
            resource = self._resources.get(resource_key)
            if resource is None:
                return {"down": False, "retry_after": 0.0, "probes": 0}
            return {
                "down": resource.down,
                "retry_after": resource.retry_after,
                "probes": resource.probes,
            }

    def shutdown(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join()

    def _queue_batches_locked(
        self, lane: ProjectLane, batches: Sequence[IndexBatch]
    ) -> None:
        for batch in batches:
            batch = replace(
                batch,
                registration_id=lane.registration_id,
                resource_key=lane.resource_key,
                seq=next(self._seq),
                split=(),
                generation=lane.generation,
            )
            lane.outstanding_keys.add(batch.key)
            heapq.heappush(lane.heap, (batch.sort_key, 0, batch))

    def _submit(self, lane: ProjectLane, batches: Sequence[IndexBatch]) -> None:
        with self._cond:
            if lane.closed:
                return
            self._queue_batches_locked(lane, batches)
            self._cond.notify_all()

    def _replace(self, lane: ProjectLane, batches: Sequence[IndexBatch]) -> None:
        """Drop all queued, not-yet-started batches and queue the new plan.

        The running batch is untouched: it keeps its generation and its event
        is still delivered and acked. Queued batches of the old generation are
        discarded (never acked) and stop counting as outstanding. A removed
        lane is a no-op: it must not be revived by a late replace.
        """
        with self._cond:
            if lane.closed:
                return
            lane.generation += 1
            for _, _, batch in lane.heap:
                lane.outstanding_keys.discard(batch.key)
            lane.heap.clear()
            self._queue_batches_locked(lane, batches)
            self._cond.notify_all()

    def _ack(self, lane: ProjectLane, batch: IndexBatch) -> None:
        with self._cond:
            lane.outstanding_keys.discard(batch.key)
            self._cond.notify_all()

    def _outstanding(self, lane: ProjectLane) -> int:
        with self._cond:
            return len(lane.outstanding_keys)

    def _status(self, lane: ProjectLane) -> dict[str, Any]:
        with self._cond:
            queued = len(lane.heap)
            in_flight = 1 if lane.in_flight is not None else 0
            held = lane.resource.down and (lane in lane.resource.held or queued > 0)
            reason = "embedding" if held else lane.pause_reason
            return {
                "queued": queued,
                "in_flight": in_flight,
                "awaiting_completion": len(lane.outstanding_keys) - queued - in_flight,
                "paused": reason is not None,
                "pause_reason": reason,
                "retry_after": self._eligible_at(lane) if reason else None,
            }

    def _unregister(self, lane: ProjectLane, wait: bool, timeout: float | None) -> bool:
        """Cancel the project's work. Returns False if a running batch was
        still running when the timeout expired."""
        with self._cond:
            if not lane.closed:
                lane.closed = True
                lane.cancelled += len(lane.heap)
                lane.heap.clear()
                lane.outstanding_keys.clear()
                lane.resource.held.discard(lane)
                if lane in self._lanes:
                    self._lanes.remove(lane)
                self._cond.notify_all()
            if wait and lane.in_flight is not None:
                return self._cond.wait_for(lambda: lane.in_flight is None, timeout)
            return lane.in_flight is None

    # -- selection ----------------------------------------------------------

    def _eligible_at(self, lane: ProjectLane) -> float:
        at = lane.paused_until or 0.0
        if lane.resource.down:
            at = max(at, lane.resource.retry_after)
        return at

    def _select(self, now: float):
        """Pick the next action under the lock: a probe or a batch to run."""
        ready = []
        for lane in self._lanes:
            if not lane.heap or lane.in_flight is not None:
                continue
            if self._eligible_at(lane) > now:
                continue
            ready.append(lane)
        if not ready:
            return None
        # A due outage probe goes first: it is cheap, runs once per resource
        # and unblocks every project waiting on the resource.
        for lane in ready:
            if lane.resource.down:
                return ("probe", lane)
        chosen = min(ready, key=lambda lane: lane.heap[0][0])
        # A lane that ran FAIRNESS_BURST batches since some other ready lane
        # last ran yields to the ready lane that has waited longest. Yielding
        # to the best-ranked other lane instead let two busy projects take
        # turns while a third waited (2026-11-06 review: batch 28 of 60).
        others = [lane for lane in ready if lane is not chosen]
        if (
            others
            and chosen.recent
            and len(chosen.recent) >= self._fairness_burst
            and chosen.recent[0] > min(lane.last_served for lane in others)
        ):
            chosen = min(others, key=lambda lane: (lane.last_served, lane.heap[0][0]))
        tick = next(self._ticks)
        chosen.last_served = tick
        chosen.recent.append(tick)
        while len(chosen.recent) > self._fairness_burst:
            chosen.recent.popleft()
        self._last_lane = chosen
        batch = heapq.heappop(chosen.heap)[2]
        chosen.in_flight = batch
        return ("batch", chosen, batch)

    def _next_deadline(self) -> float | None:
        deadlines = [
            self._eligible_at(lane)
            for lane in self._lanes
            if lane.heap and lane.in_flight is None
        ]
        return min(deadlines) if deadlines else None

    # -- execution ----------------------------------------------------------

    def run_once(self, block: bool = False) -> bool:
        """Run at most one action. Returns whether anything was executed.

        With ``block`` the call waits (without polling) until work is eligible
        or the scheduler is stopped. Tests use ``block=False`` to step the
        scheduler deterministically.
        """
        with self._cond:
            while True:
                if self._stopped:
                    return False
                action = self._select(self._clock())
                if action is not None:
                    break
                if not block:
                    return False
                deadline = self._next_deadline()
                timeout = (
                    None if deadline is None else max(0.0, deadline - self._clock())
                )
                self._cond.wait(timeout)
        if action[0] == "probe":
            self._run_probe(action[1])
        else:
            self._run_batch(action[1], action[2])
        return True

    def run_until_idle(self, limit: int = 10_000) -> int:
        """Step until nothing is eligible. For tests and synchronous callers."""
        executed = 0
        while executed < limit and self.run_once(block=False):
            executed += 1
        return executed

    def _run(self):
        logger.info("Starting indexing scheduler thread...")
        while self.run_once(block=True):
            pass

    def _run_probe(self, lane: ProjectLane):
        resource = lane.resource
        try:
            lane.probe()
        except Exception:  # noqa: BLE001  # pylint: disable=broad-except
            logger.warning("Embedding probe failed for %s", resource.key)
            ok = False
        else:
            ok = True
        events: list[tuple[ProjectLane, Any]] = []
        with self._cond:
            resource.probes += 1
            if ok:
                resource.down = False
                resource.retry_after = 0.0
                # Every project that waited on the resource hears about it
                events = [
                    (other, ResourceRecovered())
                    for other in self._lanes
                    if other.resource is resource
                    and (other in resource.held or other.heap)
                ]
                resource.held.clear()
            else:
                resource.retry_after = self._clock() + self._retry_seconds
            self._cond.notify_all()
        self._deliver(events)

    def _run_batch(self, lane: ProjectLane, batch: IndexBatch):
        failure: Exception | None = None
        logger.info(
            "Processing chunk batch of %s chunks for %s",
            len(batch.ids),
            batch.project_id,
        )
        try:
            lane.write(batch)
        except Exception as exception:  # noqa: BLE001  # pylint: disable=broad-except
            failure = exception
        probe_ok = True
        if isinstance(failure, EmbeddingError):
            # Is the model down, or is this document the problem? Decided
            # here, once for the shared resource, not by each project.
            try:
                lane.probe()
            except Exception:  # noqa: BLE001  # pylint: disable=broad-except
                probe_ok = False
        events: list[tuple[ProjectLane, Any]] = []
        with self._cond:
            lane.in_flight = None
            if lane.closed:
                # Removed while running: the upsert (if any) already happened
                # and is harmless; its result must not revive the project.
                pass
            elif failure is None:
                lane.paused_until = None
                lane.pause_reason = None
                events.append((lane, BatchCompleted(batch)))
            elif isinstance(failure, EmbeddingError):
                self._apply_embedding_failure(lane, batch, probe_ok, events)
            else:
                logger.error("Batch storage failed; retaining work", exc_info=failure)
                heapq.heappush(lane.heap, (batch.sort_key, 0, batch))
                lane.paused_until = self._clock() + self._retry_seconds
                lane.pause_reason = "storage"
            self._cond.notify_all()
        self._deliver(events)

    def _apply_embedding_failure(self, lane, batch, probe_ok, events):
        resource = lane.resource
        if not probe_ok:
            resource.down = True
            resource.retry_after = self._clock() + self._retry_seconds
            resource.held.add(lane)
            heapq.heappush(lane.heap, (batch.sort_key, 0, batch))
        elif len(batch.ids) == 1:
            events.append((lane, DocumentFailed(batch)))
        else:
            # Poison isolation: bisect; the halves keep the parent's rank/seq
            lane.outstanding_keys.discard(batch.key)
            for half in batch.halves():
                lane.outstanding_keys.add(half.key)
                heapq.heappush(lane.heap, (half.sort_key, 0, half))

    def _deliver(self, events: list[tuple[ProjectLane, Any]]):
        # Outside the lock, and always non-blocking
        for lane, event in events:
            if lane.closed:
                continue
            try:
                lane.deliver(event)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Could not deliver %s", type(event).__name__)
