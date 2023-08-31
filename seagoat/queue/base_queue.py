from collections import namedtuple
from multiprocessing import Manager
from multiprocessing import Process
from multiprocessing import Queue


Task = namedtuple("Task", ["name", "args", "kwargs"])


class BaseQueue:
    def __init__(
        self,
        *args,
        **kwargs,
    ):
        self._task_queue = Queue()
        self._worker_process = Process(
            target=self._worker_function, args=args, kwargs=kwargs
        )
        self._worker_process.start()

    def _worker_function(self, **args):
        return args

    def enqueue(self, task_name, *args, wait_for_result=True, **kwargs):
        result_queue = Manager().Queue()
        task = Task(
            name=task_name, args=args, kwargs={**kwargs, "__result_queue": result_queue}
        )
        self._task_queue.put(task)
        if wait_for_result:
            return result_queue.get()

        return None

    def shutdown(self):
        self._task_queue.put(Task(name="shutdown", args=None, kwargs=None))
        self._worker_process.join()

    def _handle_task(self, context, task: Task):
        handler_name = f"handle_{task.name}"
        handler = getattr(self, handler_name, None)
        if handler:
            kwargs = dict(task.kwargs or {})
            if "__result_queue" in kwargs:
                del kwargs["__result_queue"]
            result = handler(context, *task.args, **kwargs)
            task.kwargs.get("__result_queue").put(result)
