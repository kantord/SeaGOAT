import hashlib
import os
import pickle
from pathlib import Path
from typing import Generic, TypeVar

import appdirs

T = TypeVar("T")

# Change this whenever a new version is released that requires files to be
# re-analyzed
CACHE_FORMAT_VERSION = 29


def get_cache_root():
    if "RUNNER_TEMP" in os.environ:
        return Path(os.environ["RUNNER_TEMP"])

    return Path(
        appdirs.user_cache_dir(
            "seagoat-pytest" if "PYTEST_CURRENT_TEST" in os.environ else "seagoat"
        )
    )


class Cache(Generic[T]):
    def __init__(self, cache_name: str, path: Path, initial_value: T):
        self._path = path
        self.data = initial_value
        self._cache_name = cache_name

    def load(self):
        try:
            with open(self._get_cache_file(), "rb") as cache_file:
                self.data = pickle.load(cache_file)
        except (FileNotFoundError, pickle.UnpicklingError, EOFError):
            pass

    def persist(self):
        with open(self._get_cache_file(), "wb") as cache_file:
            pickle.dump(self.data, cache_file)

    def _get_cache_file(self):
        return self.get_cache_folder() / self._cache_name

    def get_cache_folder(self):
        cache_folder = get_cache_root() / self._get_project_hash()
        cache_folder.mkdir(parents=True, exist_ok=True)

        return (cache_folder).resolve()

    def _get_project_hash(self):
        normalized_path = Path(self._path).expanduser().resolve()
        text = f"""
        Cache version: {CACHE_FORMAT_VERSION}
        Normalized path: {normalized_path}
        """

        return hashlib.sha256(text.encode()).hexdigest()
