from pathlib import Path
import pickle
from typing import TypeVar, Generic

T = TypeVar("T")


class Cache(Generic[T]):
    def __init__(self, path: Path, initial_value: T):
        self._path = path
        self.data = initial_value

    def load(self):
        try:
            with open(self._path, "rb") as cache_file:
                self.data = pickle.load(cache_file)
        except (FileNotFoundError, pickle.UnpicklingError, EOFError):
            pass

    def persist(self):
        with open(self._path, "wb") as cache_file:
            pickle.dump(self.data, cache_file)
