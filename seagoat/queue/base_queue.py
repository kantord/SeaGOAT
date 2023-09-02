import logging
from dataclasses import dataclass
from dataclasses import field
from multiprocessing import Manager
from multiprocessing import Process
from multiprocessing import Queue
from typing import Any
from typing import Dict
from typing import Tuple


@dataclass
class Task:
    name: str
    args: Tuple[Any, ...] = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)


class BaseQueue:
    def __init__(
        self,
        **kwargs,
    ):
        self.kwargs = kwargs
        self._task_queue = Queue()
        self._worker_process = Process(target=self._worker_function)
        self._worker_process.start()

    def _get_context(self) -> Dict[str, Any]:
        low_priority_queue = Queue()

        return {
            "low_priority_queue": low_priority_queue,
        }

    def enqueue_high_prio(self, task_name, *args, wait_for_result=True, **kwargs):
        result_queue = Manager().Queue()
        task = Task(
            name=task_name, args=args, kwargs={**kwargs, "__result_queue": result_queue}
        )
        self._task_queue.put(task)
        if wait_for_result:
            return result_queue.get()

        return None

    def shutdown(self):
        self._task_queue.put(Task(name="shutdown", args=(), kwargs={}))
        self._worker_process.join()

    def _handle_task(self, context, task: Task):
        logging.info("Handling task: %s", task.name)
        handler_name = f"handle_{task.name}"
        handler = getattr(self, handler_name, None)
        if handler:
            kwargs = dict(task.kwargs or {})
            result_queue = kwargs.pop("__result_queue", None)
            result = handler(context, *task.args, **kwargs)
            if result_queue is not None:
                result_queue.put(result)

    def _worker_function(self):
        logging.info("Starting worker process...")
        context = self._get_context()
        low_priority_queue = context["low_priority_queue"]

        while True:
            while self._task_queue.qsize() == 0 and low_priority_queue.qsize() > 0:
                task = low_priority_queue.get()
                self._handle_task(context, task)

            task = self._task_queue.get()

            if task.name == "shutdown":
                break

            self._handle_task(context, task)
