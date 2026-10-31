import logging
import mmap
import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path

from stop_words import get_stop_words

from seagoat.cache import Cache
from seagoat.repository import Repository
from seagoat.result import Result
from seagoat.utils.config import get_config_values
from seagoat.utils.file_types import is_file_type_supported

logger = logging.getLogger(__name__)

KILOBYTE = 1024
# Files read per git process when building the cache
BLOB_BATCH_SIZE = 500
MEGABYTE = KILOBYTE * 1024
STOP_WORDS = set(get_stop_words("english"))
RIPGREP_CANDIDATE_MULTIPLIER = 10


def _count_distinct_matched_words(line_text: str, pattern_words: list[str]) -> int:
    """Count how many DISTINCT query words a matched line contains.

    Words are matched case-insensitively as substrings, the same literal
    words that go into the ripgrep pattern after stopword removal.
    """
    lowered_line = line_text.lower()
    return sum(1 for word in set(pattern_words) if word.lower() in lowered_line)


class RipGrepCache(str):
    def __init__(self, repository: Repository):
        cache = Cache("ripgrep", Path(repository.path), {})
        self.repository = repository
        self.file_path = cache.get_cache_folder() / "mmap"
        if platform.system() == "Windows":
            self.file_path = tempfile.mktemp()
        self.is_initialized = False
        self._data = ""
        self.config = get_config_values(Path(repository.path))

    def _iterate_files_to_cache(self):
        for file, _ in self.repository.top_files():
            yield file

    def _iterate_lines_to_cache(self):
        max_file_size_kb = self.config["server"]["ripgrep"]["maxFileSize"]
        max_file_size_bytes = max_file_size_kb * KILOBYTE
        files = list(self._iterate_files_to_cache())
        # The version in HEAD, which results are displayed from, not the
        # working tree: uncommitted lines would point past its end
        blobs = {}
        for batch_start in range(0, len(files), BLOB_BATCH_SIZE):
            batch = files[batch_start : batch_start + BLOB_BATCH_SIZE]
            blobs.update(
                self.repository.get_blobs_data([file.object_id for file in batch])
            )

        for file in files:
            file_contents = blobs.get(file.object_id, "")

            if len(file_contents) > max_file_size_bytes:
                logger.warning("Warning: file %s is too large to cache", file.path)
                continue

            for line_number, line in enumerate(file_contents.splitlines(), start=1):
                yield file, line_number, line

    def _generate_cache_lines(self):
        for file, line_number, line in self._iterate_lines_to_cache():
            # NUL separated: unlike ":", it cannot appear in a file path
            yield f"{file.path}\0{line_number}\0{line}\n"

    def _build_cache_file(self):
        total_estimated_cache_size = 0
        line_count = 0
        max_mmap_size = self.config["server"]["ripgrep"]["maxMmapSize"]
        max_mmap_size_bytes = max_mmap_size * MEGABYTE

        with open(self.file_path, "w", encoding="utf-8") as cache_file:
            for formattted_cache_line in self._generate_cache_lines():
                cache_file.write(formattted_cache_line)
                total_estimated_cache_size += len(formattted_cache_line)
                line_count += 1

                if total_estimated_cache_size > max_mmap_size_bytes:
                    logger.warning(
                        "Warning: maximum estimated ripgrep cache size of %s megabytes exceeded",
                        max_mmap_size,
                    )

                    break

        logger.info(
            "Estimated ripgrep cache size: %.2f megabytes (%s bytes). Line count %s",
            total_estimated_cache_size / MEGABYTE,
            int(total_estimated_cache_size),
            line_count,
        )
        self.is_initialized = True

    def rebuild(self):
        self._build_cache_file()
        if platform.system() == "Windows":
            # Memory map does not work on Windows for some reason
            # Use a simple string as a fallback
            with open(self.file_path, encoding="utf-8") as cache_file:
                self._data = cache_file.read()
        else:
            with open(self.file_path, "r+b") as cache_file:
                if os.fstat(cache_file.fileno()).st_size == 0:
                    # mmap() cannot map a zero-length file
                    self._data = b""
                else:
                    self._data = mmap.mmap(cache_file.fileno(), 0)

    def encode(self, *args, **kwargs):  # type: ignore
        return self._data

    def as_input(self):
        # subprocess only closes stdin for falsy input, so an empty cache
        # must be passed as "" instead of self, otherwise rg waits forever
        if not self._data:
            return ""

        if platform.system() == "Windows":
            return self.encode()

        return self


def initialize(repository: Repository):
    path = repository.path
    memory_cache = RipGrepCache(repository)

    def cache_chunk(_):
        # Ripgrep does not use chunks
        pass

    def cache_repo():
        memory_cache.rebuild()

    def _fetch(query_text: str, path: str, limit: int, cache: RipGrepCache):
        words = [word for word in query_text.split(" ") if word not in STOP_WORDS]
        query_text_without_stopwords = " ".join(words)
        if len(query_text_without_stopwords) > 2:
            query_text = query_text_without_stopwords
        query_text = re.sub(r"\s+", "|", query_text)
        # The exact literal words that go into the ripgrep pattern
        pattern_words = [word for word in query_text.split("|") if word]
        files = {}
        max_vector_distance = cache.config["server"]["chroma"]["maxVectorDistance"]
        candidate_limit = limit * RIPGREP_CANDIDATE_MULTIPLIER

        cmd = [
            "rg",
            "--max-count",
            str(candidate_limit),
            "--ignore-case",
            # The cache contains NUL separators, which would otherwise make rg
            # treat it as a binary file
            "--text",
            # -e: a query starting with "-" is a pattern, not an option
            "-e",
            query_text,
        ]

        try:
            rg_output = subprocess.check_output(
                cmd, encoding="utf-8", input=cache.as_input()
            )
        except subprocess.CalledProcessError as exception:
            rg_output = exception.output

        # (path, line number, distinct query words) in ripgrep's order
        matches = []
        for line in rg_output.splitlines():
            relative_path, raw_line_number, line_text = line.split("\0", 2)

            if not is_file_type_supported(relative_path):
                continue

            matches.append(
                (
                    relative_path,
                    int(raw_line_number),
                    _count_distinct_matched_words(line_text, pattern_words),
                )
            )

        # Keep the limit best lines overall: most distinct query words first;
        # the sort is stable, so ties keep ripgrep's order (important files
        # first)
        matches.sort(key=lambda match: -match[2])
        for relative_path, line_number, distinct_words in matches[:limit]:
            if relative_path not in files:
                files[relative_path] = Result(
                    query_text, repository.get_file(relative_path)
                )
            # A regex word (e.g. "[0-9]{2,10}") never appears literally; count
            # it as one word. This keeps ripgrep results on comparable levels
            # with chroma results.
            files[relative_path].add_line(
                line_number, max_vector_distance * 0.8 / max(distinct_words, 1)
            )

        return files.values()

    def fetch(query_text: str, limit: int):
        if not memory_cache.is_initialized:
            repository.analyze_files()
            cache_repo()

        return _fetch(query_text, str(path), limit, memory_cache)

    return {
        "fetch": fetch,
        "cache_chunk": cache_chunk,
        "cache_repo": cache_repo,
    }
