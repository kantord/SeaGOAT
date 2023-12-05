import logging
import math
import time

import orjson

from seagoat import __version__
from seagoat.queue.base_queue import LOW_PRIORITY, MEDIUM_PRIORITY, BaseQueue

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
    def _get_context(self):
        context = super()._get_context()

        from seagoat.engine import Engine

        seagoat_engine = Engine(self.kwargs["repo_path"])
        context["seagoat_engine"] = seagoat_engine
        context["last_maintenance"] = None
        context["last_repo_state_hash"] = None
        return context

    def handle_maintenance(self, context):
        if (
            context["last_maintenance"] is not None
            and time.time() - context["last_maintenance"] < SECONDS_BETWEEN_MAINTENANCE
        ):
            return

        current_repo_state_hash = context["seagoat_engine"].repository.get_status_hash()

        # Do not re-analyze repo if nothing changed
        if context["last_repo_state_hash"] == current_repo_state_hash:
            return

        context["last_repo_state_hash"] = current_repo_state_hash
        context["last_maintenance"] = time.time()

        if self._task_queue.qsize() > 0:
            return

        logging.info("Checking repository for new changes")
        remaining_chunks_to_analyze = context["seagoat_engine"].analyze_codebase(
            self.kwargs["minimum_chunks_to_analyze"]
        )

        logging.info("Analyzed the minimum number of chunks needed to operate. ")
        if remaining_chunks_to_analyze:
            logging.info(
                "Note, %s chunks need to be analyzed for optimum performance.",
                len(remaining_chunks_to_analyze),
            )

            for task_index, chunk in enumerate(remaining_chunks_to_analyze):
                priority = MEDIUM_PRIORITY + (
                    (LOW_PRIORITY - MEDIUM_PRIORITY)
                    / len(remaining_chunks_to_analyze)
                    * task_index
                )
                self.enqueue(
                    "analyze_chunk",
                    chunk,
                    priority=priority,
                    wait_for_result=False,
                )
        else:
            logging.info("Analyzed all chunks!")

    def handle_analyze_chunk(self, context, chunk):
        logging.info("Note, %s tasks left in the queue.", self._task_queue.qsize())
        logging.info("Processing chunk %s...", chunk)
        context["seagoat_engine"].process_chunk(chunk)

        if self._task_queue.qsize() == 0:
            logging.info("Analyzed all chunks!")

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
            },
            "accuracy": {
                "percentage": calculate_accuracy(analyzed_count, total_chunks),
            },
        }
