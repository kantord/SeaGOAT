import logging
import math
import time

import orjson

from seagoat import __version__
from seagoat.queue.base_queue import LOW_PRIORITY, MEDIUM_PRIORITY, BaseQueue
from seagoat.sources.chroma import EmbeddingError

logger = logging.getLogger(__name__)

SECONDS_BETWEEN_MAINTENANCE = 10

# How long a paused/backed-off indexer waits before probing/retrying again
RETRY_DEADLINE_SECONDS = 10


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
    BATCH_TASK = "analyze_batch"
    LEGACY_CHUNK_TASK = "analyze_chunk"

    def _get_context(self):
        context = super()._get_context()

        from seagoat.engine import Engine

        seagoat_engine = Engine(self.kwargs["repo_path"])
        context["seagoat_engine"] = seagoat_engine
        context["last_maintenance"] = None
        context["last_repo_state_hash"] = None
        return context

    def _ensure_recovery_state(self, context):
        context.setdefault("failed_chunks", set())
        context.setdefault("paused", False)
        context.setdefault("pause_reason", None)
        context.setdefault("retry_after", 0.0)
        context.setdefault("retained_batches", [])
        context.setdefault("replan_pending", False)

    def _enqueue_batch(self, chunks, priority, parent_name=BATCH_TASK):
        self.enqueue(
            parent_name,
            chunks,
            priority=priority,
            batch_priority=priority,
            parent_name=parent_name,
            wait_for_result=False,
        )

    def _enqueue_batches(self, context, chunks):
        if not chunks:
            return
        batch_size = context["seagoat_engine"].config["server"]["chroma"]["batchSize"]
        for start in range(0, len(chunks), batch_size):
            priority = MEDIUM_PRIORITY + (
                (LOW_PRIORITY - MEDIUM_PRIORITY) * start / len(chunks)
            )
            self._enqueue_batch(chunks[start : start + batch_size], priority)

    def handle_maintenance(self, context):
        self._ensure_recovery_state(context)
        self._run_recovery(context)
        if context["paused"]:
            return
        if (
            context["last_maintenance"] is not None
            and time.time() - context["last_maintenance"] < SECONDS_BETWEEN_MAINTENANCE
        ):
            return
        if self._has_pending_task(self.BATCH_TASK) or self._has_pending_task(
            self.LEGACY_CHUNK_TASK
        ):
            return

        engine = context["seagoat_engine"]
        current_repo_state_hash = engine.repository.get_status_hash()
        context["last_maintenance"] = time.time()
        if (
            not context["replan_pending"]
            and context["last_repo_state_hash"] == current_repo_state_hash
        ):
            return

        chunks = engine.plan_indexing(excluded_ids=context["failed_chunks"])
        self._enqueue_batches(context, chunks)
        if not chunks:
            logger.info("Analyzed all chunks!")
        # Preserve retry eligibility until planning and all enqueue calls succeed.
        context["last_repo_state_hash"] = current_repo_state_hash
        context["replan_pending"] = False

    @staticmethod
    def _probe_embedding(engine):
        for source in engine._fetchers["sync"]:
            if source.get("probe_embedding") is not None:
                source["probe_embedding"]()

    def _run_recovery(self, context):
        if context["paused"]:
            if time.monotonic() < context["retry_after"]:
                return
            if context["pause_reason"] == "embedding":
                try:
                    self._probe_embedding(context["seagoat_engine"])
                except EmbeddingError:
                    context["retry_after"] = time.monotonic() + RETRY_DEADLINE_SECONDS
                    return
                context["failed_chunks"].clear()
            context["paused"] = False
            context["pause_reason"] = None
            context["retry_after"] = 0.0
            context["replan_pending"] = True

        retained = context["retained_batches"]
        while retained:
            chunks, priority, name = retained[0]
            self._enqueue_batch(chunks, priority, name)
            # An enqueue failure must leave this batch retained for the next pass.
            retained.pop(0)

    @staticmethod
    def _retain_and_pause(context, chunks, priority, name, reason):
        context["retained_batches"].append((chunks, priority, name))
        context["paused"] = True
        context["pause_reason"] = reason
        context["retry_after"] = time.monotonic() + RETRY_DEADLINE_SECONDS

    def handle_analyze_batch(
        self, context, chunks, batch_priority=MEDIUM_PRIORITY, parent_name=BATCH_TASK
    ):
        self._ensure_recovery_state(context)
        engine = context["seagoat_engine"]
        chunks = [
            chunk
            for chunk in chunks
            if chunk.chunk_id not in engine.cache.data["chunks_already_analyzed"]
            and chunk.chunk_id not in context["failed_chunks"]
        ]
        if not chunks:
            return
        if context["paused"]:
            context["retained_batches"].append((chunks, batch_priority, parent_name))
            return

        logger.info("Processing chunk batch of %s chunks", len(chunks))
        try:
            engine.process_batch(chunks)
        except EmbeddingError:
            try:
                self._probe_embedding(engine)
            except EmbeddingError:
                self._retain_and_pause(
                    context, chunks, batch_priority, parent_name, "embedding"
                )
                return
            if len(chunks) == 1:
                failed_id = chunks[0].chunk_id
                context["failed_chunks"].add(failed_id)
                engine.cache.data["chunks_not_yet_analyzed"].discard(failed_id)
                logger.warning("Quarantining failing chunk %s", failed_id)
                return
            midpoint = len(chunks) // 2
            self._enqueue_batch(chunks[:midpoint], batch_priority, parent_name)
            self._enqueue_batch(chunks[midpoint:], batch_priority, parent_name)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Batch storage failed; retaining work for retry")
            self._retain_and_pause(
                context, chunks, batch_priority, parent_name, "storage"
            )
        else:
            if not engine.cache.data["chunks_not_yet_analyzed"]:
                logger.info("Analyzed all chunks!")

    def handle_analyze_chunk(self, context, chunk):
        """Legacy task names use the same completion and recovery path."""
        self.handle_analyze_batch(context, [chunk])

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
        analyzed_count = len(engine.cache.data["chunks_already_analyzed"])
        unanalyzed_count = len(engine.cache.data["chunks_not_yet_analyzed"])
        total_chunks = analyzed_count + unanalyzed_count

        return {
            "queue": {
                "size": self._task_queue.qsize(),
            },
            "chunks": {
                "analyzed": analyzed_count,
                "unanalyzed": unanalyzed_count,
                "failed": len(context["failed_chunks"]),
            },
            "indexing": {
                "paused": context["paused"],
            },
            "accuracy": {
                "percentage": calculate_accuracy(analyzed_count, total_chunks),
            },
        }
