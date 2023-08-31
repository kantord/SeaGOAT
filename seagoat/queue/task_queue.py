# pylint: disable=import-outside-toplevel
import logging
import math
from multiprocessing import Queue
from typing import Optional

from seagoat.queue.base_queue import BaseQueue


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

    return int(normalized_value * 100)


class TaskQueue(BaseQueue):
    def _worker_function(
        self, repo_path: str, minimum_chunks_to_analyze: Optional[int]
    ):
        logging.info("Starting worker process...")
        chunks_to_analyze = Queue()

        from seagoat.engine import Engine

        seagoat_engine = Engine(repo_path)

        remaining_chunks_to_analyze = seagoat_engine.analyze_codebase(
            minimum_chunks_to_analyze
        )

        logging.info("Analyzed the minimum number of chunks needed to operate. ")
        if remaining_chunks_to_analyze:
            logging.info(
                "Note, %s chunks need to be analyzed for optimum performance.",
                len(remaining_chunks_to_analyze),
            )
        else:
            logging.info(
                "Analyzed all chunks!",
            )

        for chunk in remaining_chunks_to_analyze:
            chunks_to_analyze.put(chunk)

        context = {
            "seagoat_engine": seagoat_engine,
            "chunks_to_analyze": chunks_to_analyze,
        }

        while True:
            while self._task_queue.qsize() == 0 and chunks_to_analyze.qsize() > 0:
                logging.info(
                    "Note, %s chunks left to analyze.", chunks_to_analyze.qsize()
                )
                chunk = chunks_to_analyze.get()
                logging.info("Processing chunk %s...", chunk)
                seagoat_engine.process_chunk(chunk)
                if chunks_to_analyze.empty():
                    logging.info(
                        "Analyzed all chunks!",
                    )

            task = self._task_queue.get()

            if task.name == "shutdown":
                break

            handler_name = f"handle_{task.name}"
            handler = getattr(self, handler_name, None)
            if handler:
                kwargs = dict(task.kwargs or {})
                if "__result_queue" in kwargs:
                    del kwargs["__result_queue"]
                result = handler(context, *task.args, **kwargs)
                task.kwargs.get("__result_queue").put(result)

    def handle_query(self, context, **kwargs):
        context["seagoat_engine"].query(kwargs["query"])
        context["seagoat_engine"].fetch_sync(
            limit_clue=kwargs["limit_clue"],
            context_above=int(kwargs["context_above"]),
            context_below=int(kwargs["context_below"]),
        )
        return context["seagoat_engine"].get_results()

    def handle_get_stats(self, context):
        engine = context["seagoat_engine"]
        chunks_to_analyze = context["chunks_to_analyze"]
        analyzed_count = len(engine.cache.data["chunks_already_analyzed"])
        unanalyzed_count = chunks_to_analyze.qsize()
        total_chunks = analyzed_count + unanalyzed_count

        return {
            "queue": {
                "size": unanalyzed_count + self._task_queue.qsize(),
            },
            "chunks": {
                "analyzed": analyzed_count,
                "unanalyzed": unanalyzed_count,
            },
            "accuracy": {
                "percentage": calculate_accuracy(analyzed_count, total_chunks),
            },
        }
