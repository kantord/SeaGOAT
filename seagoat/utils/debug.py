import time
from contextlib import contextmanager
from functools import wraps

TIMER_DICT = {}


@contextmanager
def timed_block(timer_name, count_total=False):
    before_time = time.time()
    try:
        yield
    finally:
        after_time = time.time()
        elapsed_time = after_time - before_time

        if count_total:
            TIMER_DICT[timer_name] = TIMER_DICT.get(timer_name, 0) + elapsed_time
        else:
            print(
                f"⌛ Timer '{timer_name}' took {int(elapsed_time * 1000)} milliseconds"
            )


def timed_function(timer_name, count_total=False):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with timed_block(timer_name, count_total=count_total):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def reset_timers():
    for timer_name, elapsed_time in TIMER_DICT.items():
        print(
            f"⌛ Timer '{timer_name}' accumulated {int(elapsed_time * 1000)} milliseconds"
        )

    TIMER_DICT.clear()
