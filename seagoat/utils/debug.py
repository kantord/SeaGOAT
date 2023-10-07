import time
from contextlib import contextmanager


@contextmanager
def timed_block(timer_name):
    before_time = time.time()
    try:
        yield
    finally:
        after_time = time.time()
        print(
            f"⌛ Timer '{timer_name}' took {int((after_time - before_time)* 1000)} milliseconds"
        )
