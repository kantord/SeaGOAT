import re
from pathlib import Path

from ripgrepy import Ripgrepy

from seagoat.common import SUPPORTED_FILE_TYPES
from seagoat.repository import Repository
from seagoat.result import Result
from seagoat.sources.chroma import MAXIMUM_VECTOR_DISTANCE


def _fetch(query_text: str, path: str, limit: int):
    query_text = re.sub(r"\s+", "|", query_text)
    files = {}
    for result in (
        Ripgrepy(query_text, path)
        .max_count(limit)
        .ignore_case()
        .max_filesize("200K")
        .json()
        .run()
        .as_dict
    ):
        result_data = result["data"]
        absolute_path = result_data["path"]["text"]
        relative_path = Path(absolute_path).relative_to(path)
        line_number = int(result_data["line_number"])

        if relative_path.suffix not in SUPPORTED_FILE_TYPES:
            continue

        if relative_path not in files:
            files[relative_path] = Result(str(relative_path), absolute_path)

        # This is so that ripgrep results are on comparable levels with chroma results
        files[relative_path].add_line(line_number, MAXIMUM_VECTOR_DISTANCE * 0.8)

    return files.values()


def initialize(repository: Repository):
    path = repository.path

    def fetch(query_text: str, limit: int):
        return _fetch(query_text, str(path), limit)

    def cache_chunk(_):
        # Ripgrep does not need a cache for chunks
        pass

    return {
        "fetch": fetch,
        "cache_chunk": cache_chunk,
    }
