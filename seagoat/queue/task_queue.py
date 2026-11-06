import logging
import math
import time

import orjson

from seagoat import __version__
from seagoat.engine import RepositoryChanged
from seagoat.queue.base_queue import HIGH_PRIORITY, LOW_PRIORITY, BaseQueue
from seagoat.queue.indexing_scheduler import (
    RETRY_DEADLINE_SECONDS,
    BatchCompleted,
    DocumentFailed,
    IndexingScheduler,
    ResourceRecovered,
    make_batches,
)
from seagoat.sources import chroma

logger = logging.getLogger(__name__)

SECONDS_BETWEEN_MAINTENANCE = 10


def calculate_accuracy(chunks_analyzed: int, total_chunks: int) -> int:
    if total_chunks == 0 or total_chunks - chunks_analyzed == 0:
        return 100

    progress = chunks_analyzed / total_chunks

    k = 10
    x_0 = 0.25

    f_x = 1 / (1 + math.exp(-k * (progress - x_0)))
    f_0 = 1 / (1 + math.exp(k * x_0))
    f_1 = 1 / (1 + math.exp(-k * (1 - x_0)))

    normalized_value = (f_x - f_0) / (f_1 - f_0)
    percentage_value = normalized_value * 100
    rounded_percentage_value = int(percentage_value)

    if percentage_value > 0 and rounded_percentage_value == 0:
        return 1

    return rounded_percentage_value


class TaskQueue(BaseQueue):
    """One project's queue: queries, stats, planning and cleanup.

    Embedding and upserting happens in the process-wide
    :class:`~seagoat.queue.indexing_scheduler.IndexingScheduler`. This queue
    plans work, submits self-contained batches, and is the only place that
    publishes their completion and prunes stale rows.
    """

    PRUNE_TASK = "prune_index"
    EVENT_TASK = "index_event"
    # Stale-row deletions are scheduled as bounded low-priority tasks so
    # priority-zero queries/stats interleave and cleanup never starves them.
    PRUNE_BATCH_SIZE = 1000

    def _has_pending_indexing_tasks(self) -> bool:
        """Whether cleanup work is still waiting in this queue."""
        return self._has_pending_task(self.PRUNE_TASK)

    @staticmethod
    def _outstanding(context) -> int:
        """Batches submitted to the global scheduler and not yet acked."""
        return context["lane"].outstanding()

    def get_maintenance_deadline(self, context) -> float | None:
        """Absolute monotonic deadline for the next maintenance pass.

        ``None`` defers ordinary maintenance until the next task wakes the
        worker: while global jobs are outstanding (their completion events
        wake it) or cleanup is queued. A paused context still runs its own
        recovery at ``retry_after``.
        """
        self._ensure_recovery_state(context)
        if context["paused"]:
            return context["retry_after"]
        if self._has_pending_indexing_tasks():
            return None
        if context["last_maintenance"] is None:
            return 0.0
        return context["last_maintenance"] + SECONDS_BETWEEN_MAINTENANCE

    def _get_context(self):
        context = super()._get_context()

        from seagoat.engine import Engine

        seagoat_engine = Engine(self.kwargs["repo_path"])
        context["seagoat_engine"] = seagoat_engine
        context["last_maintenance"] = None
        context["last_repo_state_hash"] = None
        scheduler = self.kwargs.get("scheduler") or IndexingScheduler.shared()
        context["lane"] = scheduler.register(
            self.kwargs["repo_path"],
            seagoat_engine.embedding_resource_key(),
            write=seagoat_engine.write_batch,
            probe=seagoat_engine.probe_embedding,
            deliver=self._deliver_index_event,
        )
        self._lane = context["lane"]
        return context

    def _deliver_index_event(self, event):
        # Called on the scheduler thread: must never wait for this queue
        self.enqueue(
            self.EVENT_TASK, event, priority=HIGH_PRIORITY, wait_for_result=False
        )

    def shutdown(self):
        """Cancel pending indexing, wait out a running batch, stop the worker."""
        lane = getattr(self, "_lane", None)
        if lane is not None:
            lane.unregister(wait=False)
        super().shutdown()

    def handle_worker_exit(self, context):
        # After this returns no write of this project can still be running
        context["lane"].unregister(wait=True)

    def _ensure_recovery_state(self, context):
        context.setdefault("failed_chunks", set())
        context.setdefault("paused", False)
        context.setdefault("pause_reason", None)
        context.setdefault("retry_after", 0.0)
        context.setdefault("replan_pending", False)
        context.setdefault("replan_after_drain", False)

    def _submit_batches(self, context, chunks):
        # Always replace, also with an empty plan: queued batches of an older
        # plan must not keep running when nothing of them is current any more.
        engine = context["seagoat_engine"]
        lane = context["lane"]
        batches = make_batches(
            lane.project_id,
            lane.registration_id,
            lane.resource_key,
            chunks,
            engine.config["server"]["chroma"]["batchSize"],
            chroma.chunk_metadata,
        )
        lane.replace(batches)

    def handle_maintenance(self, context):
        self._ensure_recovery_state(context)
        self._run_recovery(context)
        if context["paused"]:
            return
        if (
            context["last_maintenance"] is not None
            and time.monotonic() - context["last_maintenance"]
            < SECONDS_BETWEEN_MAINTENANCE
        ):
            return
        engine = context["seagoat_engine"]
        current_repo_state_hash = engine.repository.get_status_hash()
        context["last_maintenance"] = time.monotonic()
        drained = not self._outstanding(context)
        if (
            not context["replan_pending"]
            and not (context["replan_after_drain"] and drained)
            and context["last_repo_state_hash"] == current_repo_state_hash
        ):
            return

        # The batch that is running while this replans may be planned again.
        # Its rows are idempotent upserts, so a second write is harmless; not
        # planning them would lose them if that batch fails and its split
        # halves are dropped by the replace below.
        chunks = engine.plan_indexing(excluded_ids=context["failed_chunks"])
        self._submit_batches(context, chunks)
        if not chunks:
            logger.info("Analyzed all chunks!")
        # Cleanup starts only once no global job can still write: right away
        # when nothing was submitted, otherwise after the last completion.
        self._enqueue_prune_if_needed(context)
        # Preserve retry eligibility until planning and submission succeed.
        context["last_repo_state_hash"] = current_repo_state_hash
        context["replan_pending"] = False
        if drained:
            context["replan_after_drain"] = False

    def _enqueue_prune_if_needed(self, context):
        if (
            not context["paused"]
            and not self._outstanding(context)
            and context["seagoat_engine"].pending_prune_count()
            and not self._has_pending_task(self.PRUNE_TASK)
        ):
            self.enqueue(
                self.PRUNE_TASK,
                priority=LOW_PRIORITY,
                wait_for_result=False,
            )

    def _run_recovery(self, context):
        """Recover from a project-local cleanup (storage) failure."""
        if context["paused"]:
            if time.monotonic() < context["retry_after"]:
                return
            context["paused"] = False
            context["pause_reason"] = None
            context["retry_after"] = 0.0
            context["replan_pending"] = True
        self._enqueue_prune_if_needed(context)

    @staticmethod
    def _pause_indexing(context, reason):
        context["paused"] = True
        context["pause_reason"] = reason
        context["retry_after"] = time.monotonic() + RETRY_DEADLINE_SECONDS

    def handle_index_event(self, context, event):
        """Project-owned completion path for events from the scheduler.

        Progress is published here, on this queue's worker, and only after the
        scheduler reported a successful upsert; the batch is acked last so
        that ``outstanding() == 0`` implies every result has been published.
        """
        self._ensure_recovery_state(context)
        lane = context["lane"]
        engine = context["seagoat_engine"]
        if lane.is_closed():
            # Removed project: a late event must not revive anything
            return
        if isinstance(event, BatchCompleted):
            engine.complete_batch(event.batch.ids)
            lane.ack(event.batch)
            if event.batch.generation < lane.plan_generation():
                # Rows this batch wrote may be stale in the newer plan, whose
                # stale list could not see them. Plan once more after the
                # backlog drains (pruning cannot run before that anyway).
                # Replanning right away would make the batch running then
                # old as well, and replan again on every completion.
                context["replan_after_drain"] = True
            if not engine.get_indexing_stats()["pending"]:
                logger.info("Analyzed all chunks!")
        elif isinstance(event, DocumentFailed):
            failed_ids = set(event.batch.ids)
            context["failed_chunks"].update(failed_ids)
            engine.discard_pending(failed_ids)
            logger.warning("Quarantining failing chunk(s) %s", sorted(failed_ids))
            lane.ack(event.batch)
        elif isinstance(event, ResourceRecovered):
            # Chunks quarantined around an outage get another chance
            context["failed_chunks"].clear()
            context["replan_pending"] = True
        self._enqueue_prune_if_needed(context)

    def handle_prune_index(self, context):
        """Delete a bounded batch of stale Chroma rows from the current plan.

        Runs only while no global job is outstanding, so deletion never
        overlaps an in-flight write. A repository change during pruning is
        normal and merely defers the candidates: it logs without pausing and
        sets replan_pending. Real storage errors abort instead, pausing with
        "storage"; both keep quarantine and the maintenance hash untouched, so
        the next maintenance replans and re-enqueues the candidates.
        """
        self._ensure_recovery_state(context)
        if context["paused"] or self._outstanding(context):
            return
        engine = context["seagoat_engine"]
        try:
            engine.prune_stale(self.PRUNE_BATCH_SIZE)
        except RepositoryChanged:
            logger.info("Prune skipped: repository changed since planning; will replan")
            context["replan_pending"] = True
        except Exception:  # pylint: disable=broad-except
            logger.exception("Prune failed; will replan and retry")
            context["replan_pending"] = True
            self._pause_indexing(context, "storage")
        else:
            self._enqueue_prune_if_needed(context)

    def handle_query(self, context, **kwargs):
        results = context["seagoat_engine"].query_sync(
            kwargs["query"],
            limit_clue=kwargs["limit_clue"],
            context_above=int(kwargs["context_above"]),
            context_below=int(kwargs["context_below"]),
        )
        formatted_results = [result.to_json() for result in results]

        serialized_results = orjson.dumps(
            {
                "results": formatted_results,
                "version": __version__,
            }
        )

        return serialized_results

    def handle_get_stats(self, context):
        engine = context["seagoat_engine"]
        self._ensure_recovery_state(context)
        # Cheap engine counters: no whole-collection reads per stats request.
        indexing_stats = engine.get_indexing_stats(context["failed_chunks"])
        scheduled = context["lane"].status()
        analyzed_count = indexing_stats["analyzed"]
        unanalyzed_count = indexing_stats["pending"]
        total_chunks = analyzed_count + unanalyzed_count

        return {
            "queue": {
                "size": self._task_queue.qsize(),
            },
            "chunks": {
                "analyzed": analyzed_count,
                "unanalyzed": unanalyzed_count,
                "failed": indexing_stats["failed"],
            },
            "indexing": {
                "paused": context["paused"] or scheduled["paused"],
                "pause_reason": (context["pause_reason"] if context["paused"] else None)
                or scheduled["pause_reason"],
                "queued": scheduled["queued"],
                "in_flight": scheduled["in_flight"],
                "awaiting_completion": scheduled["awaiting_completion"],
            },
            "accuracy": {
                "percentage": calculate_accuracy(analyzed_count, total_chunks),
            },
        }
