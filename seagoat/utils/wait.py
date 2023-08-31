import time


def wait_for(condition_function, timeout, period=0.05):
    start_time = time.time()
    while not condition_function():
        if time.time() - start_time > timeout:
            raise TimeoutError("Timeout expired while waiting for condition.")
        time.sleep(period)
