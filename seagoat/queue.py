# pylint: disable=import-outside-toplevel
from collections import namedtuple
from multiprocessing import Manager
from multiprocessing import Process
from multiprocessing import Queue


Task = namedtuple("Task", ["name", "args", "kwargs"])


class TaskQueue:
    def __init__(self, repo_path: str):
        self._task_queue = Queue()
        self._worker_process = Process(target=self._worker_function, args=(repo_path,))
        self._worker_process.start()

    def _worker_function(self, repo_path: str):
        from seagoat.engine import Engine

        seagoat_engine = Engine(repo_path)
        seagoat_engine.analyze_codebase()
        context = {
            "seagoat_engine": seagoat_engine,
        }

        while True:
            task = self._task_queue.get()

            if task.name == "shutdown":
                break

            handler_name = f"handle_{task.name}"
            handler = getattr(self, handler_name, None)
            if handler:
                result = handler(context, *task.args, **task.kwargs)
                task.kwargs.get("result_queue").put(result)

    def handle_query(self, context, **kwargs):
        context["seagoat_engine"].query(kwargs["query"])
        context["seagoat_engine"].fetch_sync(
            limit_clue=kwargs["limit_clue"],
            context_above=int(kwargs["context_above"]),
            context_below=int(kwargs["context_below"]),
        )
        return context["seagoat_engine"].get_results()

    def enqueue(self, task_name, *args, **kwargs):
        result_queue = Manager().Queue()
        task = Task(
            name=task_name, args=args, kwargs={**kwargs, "result_queue": result_queue}
        )
        self._task_queue.put(task)
        return result_queue.get()

    def shutdown(self):
        self._task_queue.put(Task(name="shutdown", args=None, kwargs=None))
        self._worker_process.join()
