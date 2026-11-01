import logging
import threading
import time
from dataclasses import dataclass, field
from itertools import count
from queue import Empty, PriorityQueue
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# How long to wait before retrying maintenance after it failed
MAINTENANCE_RETRY_DELAY_SECONDS = 10

# How long the worker may go without maintenance before running it after a task
MAINTENANCE_MAX_DELAY_SECONDS = 1.0

# How long a caller waits for a task result before giving up
TASK_TIMEOUT_SECONDS = 120

HIGH_PRIORITY = 0.0
MEDIUM_PRIORITY = 0.5
LOW_PRIORITY = 1.0

_TASK_SEQUENCE = count()


@dataclass(order=True)
class Task:
    priority: float
    name: str = field(compare=False)
    args: tuple[Any, ...] = field(default_factory=tuple, compare=False)
    kwargs: dict[str, Any] = field(default_factory=dict, compare=False)
    task_id: str = field(default_factory=lambda: uuid4().hex, compare=False)
    _sequence: int = field(
        default_factory=lambda: next(_TASK_SEQUENCE),
        init=False,
        repr=False,
        compare=True,
    )


class TaskFailed(Exception):
    """A task raised an exception in the worker thread"""


class TaskTimedOut(Exception):
    """A task did not produce a result within the time limit"""


class BaseQueue:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._task_queue = PriorityQueue()
        # When maintenance may run again after a failure, and when it last ran
        self._next_maintenance = 0.0
        self._last_maintenance = 0.0
        # A daemon thread does not keep the process alive on its own
        self._worker_thread = threading.Thread(
            target=self._worker_function, daemon=True
        )
        self._worker_thread.start()

    def _get_context(self) -> dict[str, Any]:
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
            try:
                result = result_queue.get(timeout=TASK_TIMEOUT_SECONDS)
            except Empty:
                # The worker may still finish the task later, but each call
                # owns a private result queue, so a late result is dropped
                # and can never be delivered to a later caller.
                raise TaskTimedOut(
                    f"Task '{task_name}' did not finish in time "
                    f"({TASK_TIMEOUT_SECONDS} seconds)"
                ) from None
            if isinstance(result, TaskFailed):
                raise result
            return result
        return None

    def handle_maintenance(self, context):
        pass

    def _has_pending_task(self, task_name: str) -> bool:
        """Whether a task with this name is waiting in the queue."""
        with self._task_queue.mutex:
            return any(task.name == task_name for task in self._task_queue.queue)

    def shutdown(self):
        self._task_queue.put(
            Task(priority=HIGH_PRIORITY, name="shutdown", args=(), kwargs={})
        )
        self._worker_thread.join()

    def _handle_task(self, context, task: Task, context_error=None):
        logger.info("Handling task: %s", task.name)
        handler_name = f"handle_{task.name}"
        handler = getattr(self, handler_name, None)
        kwargs = dict(task.kwargs or {})
        result_queue = kwargs.pop("__result_queue", None)
        if context_error is not None:
            # No context means no task can run, so each one fails instead of waiting
            result = TaskFailed(f"Context failed to initialize: {context_error}")
        elif handler is None:
            result = TaskFailed(f"Unknown task: {task.name}")
        else:
            try:
                result = handler(context, *task.args, **kwargs)
            except Exception as exception:  # pylint: disable=broad-except
                # There is only one worker thread: if a failing task ended it,
                # every later task would wait for a result forever
                logger.exception("Task %s failed", task.name)
                result = TaskFailed(f"{task.name} failed: {exception}")
        if result_queue is not None:
            result_queue.put(result)

    def _run_maintenance_if_allowed(self, context, context_error):
        """Run maintenance unless the context failed or a retry delay is active."""
        if context_error is not None:
            return
        now = time.monotonic()
        if now < self._next_maintenance:
            return
        self._last_maintenance = now
        try:
            self.handle_maintenance(context)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Maintenance failed")
            self._next_maintenance = time.monotonic() + MAINTENANCE_RETRY_DELAY_SECONDS

    def _worker_function(self):
        logger.info("Starting worker thread...")
        try:
            context = self._get_context()
            context_error = None
        except Exception as exception:  # pylint: disable=broad-except
            logger.exception("Failed to build context")
            context = None
            context_error = exception
        while True:
            try:
                task = self._task_queue.get(timeout=0.1)
                if task.name == "shutdown":
                    break
                self._handle_task(context, task, context_error=context_error)
                # Under a steady stream of tasks the queue is never empty, so
                # also run maintenance (indexing) when it is overdue
                overdue = (
                    time.monotonic() - self._last_maintenance
                    >= MAINTENANCE_MAX_DELAY_SECONDS
                )
                if overdue:
                    self._run_maintenance_if_allowed(context, context_error)
            except Empty:
                self._run_maintenance_if_allowed(context, context_error)
