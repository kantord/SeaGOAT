import logging
import threading
import time
from dataclasses import dataclass, field
from queue import Empty, PriorityQueue
from typing import Any, Dict, Tuple
from uuid import uuid4

# How long to wait before retrying maintenance after it failed
MAINTENANCE_RETRY_DELAY_SECONDS = 10

HIGH_PRIORITY = 0.0
MEDIUM_PRIORITY = 0.5
LOW_PRIORITY = 1.0


@dataclass(order=True)
class Task:
    priority: float
    name: str
    args: Tuple[Any, ...] = field(default_factory=tuple, compare=False)
    kwargs: Dict[str, Any] = field(default_factory=dict, compare=False)
    task_id: str = field(default_factory=lambda: uuid4().hex, compare=True)


class TaskFailed(Exception):
    """A task raised an exception in the worker thread"""


class BaseQueue:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._task_queue = PriorityQueue()
        # A daemon thread does not keep the process alive on its own
        self._worker_thread = threading.Thread(
            target=self._worker_function, daemon=True
        )
        self._worker_thread.start()

    def _get_context(self) -> Dict[str, Any]:
        return {}

    def enqueue(
        self,
        task_name,
        *args,
        priority=HIGH_PRIORITY,
        wait_for_result=True,
        **kwargs,
    ):
        result_queue = PriorityQueue()
        task = Task(
            priority=priority,
            name=task_name,
            args=args,
            kwargs={**kwargs, "__result_queue": result_queue},
        )
        self._task_queue.put(task)
        if wait_for_result:
            result = result_queue.get()
            if isinstance(result, TaskFailed):
                raise result
            return result
        return None

    def handle_maintenance(self, context):
        pass

    def shutdown(self):
        self._task_queue.put(
            Task(priority=HIGH_PRIORITY, name="shutdown", args=(), kwargs={})
        )
        self._worker_thread.join()

    def _handle_task(self, context, task: Task):
        logging.info("Handling task: %s", task.name)
        handler_name = f"handle_{task.name}"
        handler = getattr(self, handler_name, None)
        kwargs = dict(task.kwargs or {})
        result_queue = kwargs.pop("__result_queue", None)
        if handler is None:
            result = TaskFailed(f"Unknown task: {task.name}")
        else:
            try:
                result = handler(context, *task.args, **kwargs)
            except Exception as exception:  # pylint: disable=broad-except
                # There is only one worker thread: if a failing task ended it,
                # every later task would wait for a result forever
                logging.exception("Task %s failed", task.name)
                result = TaskFailed(f"{task.name} failed: {exception}")
        if result_queue is not None:
            result_queue.put(result)

    def _worker_function(self):
        logging.info("Starting worker thread...")
        context = self._get_context()
        next_maintenance = 0.0

        while True:
            try:
                task = self._task_queue.get(timeout=0.1)
                if task.name == "shutdown":
                    break
                self._handle_task(context, task)
            except Empty:
                if time.monotonic() < next_maintenance:
                    continue
                try:
                    self.handle_maintenance(context)
                except Exception:  # pylint: disable=broad-except
                    logging.exception("Maintenance failed")
                    next_maintenance = (
                        time.monotonic() + MAINTENANCE_RETRY_DELAY_SECONDS
                    )
