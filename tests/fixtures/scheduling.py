"""Deterministic helpers for driving TaskQueue handlers with a private scheduler."""

from queue import Empty

from seagoat.queue.indexing_scheduler import IndexingScheduler


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def manual_scheduler(clock=None, **kwargs):
    """A scheduler without a thread: tests step it with run_once/run_until_idle."""
    return IndexingScheduler(clock=clock or FakeClock(), start=False, **kwargs)


def attach_lane(queue, context, scheduler=None, resource_key=None):
    """Register the context's engine with a (private) scheduler."""
    scheduler = scheduler or manual_scheduler()
    engine = context["seagoat_engine"]
    lane = scheduler.register(
        str(engine.path),
        resource_key if resource_key is not None else engine.embedding_resource_key(),
        write=engine.write_batch,
        probe=engine.probe_embedding,
        deliver=queue._deliver_index_event,
    )
    context["lane"] = lane
    queue._lane = lane
    context["scheduler"] = scheduler
    return lane


def drive(queue, context, handled=None):
    """Alternate scheduler steps and project tasks until both are idle."""
    handled = handled if handled is not None else []
    scheduler = context["scheduler"]
    while True:
        progressed = scheduler.run_until_idle() > 0
        try:
            task = queue._task_queue.get_nowait()
        except Empty:
            if not progressed:
                return handled
            continue
        handler = getattr(queue, "handle_" + task.name)
        kwargs = dict(task.kwargs or {})
        kwargs.pop("__result_queue", None)
        handler(context, *task.args, **kwargs)
        handled.append((task.name, task.priority))
