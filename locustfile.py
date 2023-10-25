import random

from locust import HttpUser, between, task

WORDS = [
    "function",
    "where",
    "display",
    "print",
    "handle",
    "test",
    "component",
    "user",
    "basket",
    "execute",
    "compute",
    "store",
    "api",
    "endpoint",
    "request",
    "response",
    "mobile",
    "document",
    "interface",
    "web",
    "database",
    "source",
    "deploy",
    "library",
    "framework",
    "method",
    "protocol",
    "route",
]


def random_phrase():
    phrase_length = random.randint(3, 15)
    return " ".join(random.choices(WORDS, k=phrase_length))


class BaseUser(HttpUser):
    @task(8)
    def query_endpoint(self):
        phrase = random_phrase()
        self.client.get(f"/query/{phrase}")


class ShortWaitUser(BaseUser):
    wait_time = between(0.3, 1.2)

    @task(4)
    def execute_tasks_short_wait(self):
        self.query_endpoint()


class LongWaitUser(BaseUser):
    wait_time = between(1.2, 15)

    @task(6)
    def execute_tasks_long_wait(self):
        self.query_endpoint()
