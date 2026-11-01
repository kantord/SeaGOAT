import hashlib
import os
import pickle
import tempfile
from pathlib import Path
from typing import Generic, TypeVar

from seagoat.utils.paths import get_cache_dir

T = TypeVar("T")

# Change this whenever a new version is released that requires files to be
# re-analyzed
CACHE_FORMAT_VERSION = 29


class Cache(Generic[T]):
    def __init__(self, cache_name: str, path: Path, initial_value: T):
        self._path = path
        self.data = initial_value
        self._cache_name = cache_name

    def load(self):
        try:
            with open(self._get_cache_file(), "rb") as cache_file:
                # Only our own persisted cache is ever deserialized, not untrusted input
                self.data = pickle.load(cache_file)  # noqa: S301  (self-written cache, not untrusted)
        except (FileNotFoundError, pickle.UnpicklingError, EOFError):
            pass

    def persist(self):
        cache_file = self._get_cache_file()
        temp_path = None
        try:
            # Serialize to a uniquely named temporary file in the same directory
            # and only then atomically replace the real cache file, so a failure
            # while writing never corrupts the previously persisted data. The
            # temporary file is closed before being moved for Windows compatibility.
            fd, temp_path = tempfile.mkstemp(
                dir=cache_file.parent,
                prefix=f".{self._cache_name}.",
                suffix=".tmp",
            )
            with os.fdopen(fd, "wb") as temp_file:
                pickle.dump(self.data, temp_file)
            # The temporary file is closed and fully written before the swap.
            os.replace(temp_path, cache_file)
            temp_path = None
        except BaseException:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass
            raise

    def _get_cache_file(self):
        return self.get_cache_folder() / self._cache_name

    def get_cache_folder(self):
        cache_folder = get_cache_dir() / self._get_project_hash()
        cache_folder.mkdir(parents=True, exist_ok=True)

        return (cache_folder).resolve()

    def _get_project_hash(self):
        normalized_path = Path(self._path).expanduser().resolve()
        text = f"""
        Cache version: {CACHE_FORMAT_VERSION}
        Normalized path: {normalized_path}
        """

        return hashlib.sha256(text.encode()).hexdigest()
