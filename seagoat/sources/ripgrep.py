from pathlib import Path

from ripgrepy import Ripgrepy

from seagoat.common import SUPPORTED_FILE_TYPES
from seagoat.repository import Repository
from seagoat.result import Result


def _fetch(query_text: str, path: str):
    files = {}
    for result in Ripgrepy(query_text, path).json().run().as_dict:
        result_data = result["data"]
        absolute_path = result_data["path"]["text"]
        relative_path = Path(absolute_path).relative_to(path)
        line_number = int(result_data["line_number"])

        if relative_path.suffix not in SUPPORTED_FILE_TYPES:
            continue

        if relative_path not in files:
            files[relative_path] = Result(str(relative_path), absolute_path)

        files[relative_path].add_line(line_number, 0.0)

    return files.values()


def initialize(repository: Repository):
    path = repository.path

    def fetch(query_text: str):
        return _fetch(query_text, path)

    def cache_chunk(_):
        # Ripgrep does not need a cache for chunks
        pass

    def persist():
        # Ripgrep does not need persistence
        pass

    return {
        "fetch": fetch,
        "cache_chunk": cache_chunk,
        "persist": persist,
    }
