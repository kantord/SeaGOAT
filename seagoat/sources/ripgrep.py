import bisect
import logging
import mmap
import os
import platform
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


def _is_utf8_encodable(char: str) -> bool:
    try:
        char.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def query_terms(query_text: str) -> list[str]:
    """Split a query into cleaned, non-stop-word terms for ripgrep."""
    cleaned_tokens = []
    for token in query_text.split():
        cleaned_token = "".join(
            char for char in token if char != "\x00" and _is_utf8_encodable(char)
        )
        if cleaned_token:
            cleaned_tokens.append(cleaned_token)

    terms = [token for token in cleaned_tokens if token.lower() not in STOP_WORDS]

    if not terms:
        terms = cleaned_tokens

    return terms


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
        self.file_paths: list[str] = []
        self.cumulative_line_counts: list[int] = []

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

    def _build_cache_file(self):
        self.file_paths = []
        self.cumulative_line_counts = []
        total_estimated_cache_size = 0
        running_total = 0
        line_count = 0
        max_mmap_size = self.config["server"]["ripgrep"]["maxMmapSize"]
        max_mmap_size_bytes = max_mmap_size * MEGABYTE

        with open(self.file_path, "w", encoding="utf-8") as cache_file:
            for file, _, line in self._iterate_lines_to_cache():
                if not self.file_paths or self.file_paths[-1] != file.path:
                    self.file_paths.append(file.path)
                    self.cumulative_line_counts.append(running_total)

                cache_line = f"{line}\n"
                cache_file.write(cache_line)
                total_estimated_cache_size += len(cache_line)
                running_total += 1
                line_count += 1
                self.cumulative_line_counts[-1] = running_total

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


def map_global_line_to_file(cumulative: list[int], global_line: int) -> tuple[int, int]:
    index = bisect.bisect_left(cumulative, global_line)
    start = cumulative[index - 1] if index > 0 else 0
    return index, global_line - start


def run_ripgrep(cache_input, terms: list[str], max_count: int) -> list[tuple[int, str]]:
    # Before the emptiness check: a RipGrepCache is a str subclass whose own
    # value is "", its data (mmap or bytes) only comes out of encode()
    if isinstance(cache_input, str):
        cache_input = cache_input.encode("utf-8")
    if isinstance(cache_input, str):
        # On Windows, RipGrepCache.encode() returns its data as a plain str
        cache_input = str.encode(cache_input, "utf-8")
    if not cache_input or not terms:
        return []
    terms = [term for term in terms if "\n" not in term]
    if not terms:
        return []

    def build_cmd(with_fixed_strings: bool):
        cmd = [
            "rg",
            "--no-config",
            "--line-number",
            "--ignore-case",
            "--max-count",
            str(max_count),
        ]
        if with_fixed_strings:
            cmd.append("--fixed-strings")
        for term in terms:
            cmd += ["-e", term]
        return cmd

    result = subprocess.run(
        build_cmd(False), input=cache_input, capture_output=True, check=False
    )
    if result.returncode == 2:
        result = subprocess.run(
            build_cmd(True), input=cache_input, capture_output=True, check=False
        )
    if result.returncode == 2:
        raise RuntimeError(result.stderr)
    if result.returncode == 1:
        return []

    matches = []
    for line in result.stdout.splitlines():
        number, _, text = line.partition(b":")
        matches.append((int(number), text.decode("utf-8", "replace")))
    return matches


def initialize(repository: Repository):
    path = repository.path
    memory_cache = RipGrepCache(repository)

    def cache_chunk(_):
        # Ripgrep does not use chunks
        pass

    def cache_repo():
        memory_cache.rebuild()

    def _fetch(query_text: str, path: str, limit: int, cache: RipGrepCache):
        terms = query_terms(query_text)
        # The exact literal words that go into the ripgrep pattern
        pattern_words = terms
        query_text = " ".join(terms)
        files = {}
        max_vector_distance = cache.config["server"]["chroma"]["maxVectorDistance"]
        candidate_limit = limit * RIPGREP_CANDIDATE_MULTIPLIER

        # (path, line number, distinct query words) in ripgrep's order
        matches = []
        for global_line, line_text in run_ripgrep(
            cache.as_input(), terms, candidate_limit
        ):
            file_index, raw_line_number = map_global_line_to_file(
                cache.cumulative_line_counts, global_line
            )
            relative_path = cache.file_paths[file_index]

            if not is_file_type_supported(relative_path):
                continue

            matches.append(
                (
                    relative_path,
                    raw_line_number,
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
