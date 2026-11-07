import bisect
import logging
import mmap
import os
import platform
import subprocess
import tempfile
import threading
from pathlib import Path

from stop_words import get_stop_words

from seagoat.cache import Cache
from seagoat.repository import Repository, RepositorySnapshot
from seagoat.result import Result
from seagoat.snapshot import QuerySnapshot
from seagoat.utils.config import get_config_values
from seagoat.utils.file_types import is_file_type_supported

logger = logging.getLogger(__name__)

KILOBYTE = 1024
# Files read per git process when building the cache
BLOB_BATCH_SIZE = 500
MEGABYTE = KILOBYTE * 1024
STOP_WORDS = set(get_stop_words("english"))
# How many matching lines ripgrep may return before they are ranked. Lines
# arrive in file-importance order, so a small window would hide a better
# line in a less important file; the cap only bounds memory on huge repos.
RIPGREP_MAX_CANDIDATES = 50_000


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


class RipGrepCache:
    """Immutable ripgrep input built from one repository snapshot.

    The contents are written to a uniquely named file, mapped, and (where the
    platform allows) the file is unlinked right away: the mapping keeps the data
    alive for as long as it is open and no file can leak. Nothing is ever
    rewritten in place, so a mapping other readers hold stays valid; a rebuild
    makes a new instance instead of reusing this one.
    """

    def __init__(self, repository: Repository, snapshot: RepositorySnapshot):
        self.repository = repository
        self.snapshot = snapshot
        self.config = get_config_values(Path(repository.path))
        self.file_paths: list[str] = []
        self.cumulative_line_counts: list[int] = []
        self._data: mmap.mmap | str | bytes = b""
        self._closed = False
        self._build()

    def _iterate_lines_to_cache(self):
        max_file_size_kb = self.config["server"]["ripgrep"]["maxFileSize"]
        max_file_size_bytes = max_file_size_kb * KILOBYTE
        files = [file for file, _ in self.snapshot.top_files()]
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

    def _write_cache_file(self, cache_file):
        total_estimated_cache_size = 0
        line_count = 0
        max_mmap_size = self.config["server"]["ripgrep"]["maxMmapSize"]
        max_mmap_size_bytes = max_mmap_size * MEGABYTE

        for file, _, line in self._iterate_lines_to_cache():
            if not self.file_paths or self.file_paths[-1] != file.path:
                self.file_paths.append(file.path)
                self.cumulative_line_counts.append(line_count)

            cache_line = f"{line}\n"
            cache_file.write(cache_line)
            total_estimated_cache_size += len(cache_line)
            line_count += 1
            self.cumulative_line_counts[-1] = line_count

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

    def _build(self):
        cache_folder = Cache(
            "ripgrep", Path(self.repository.path), {}
        ).get_cache_folder()
        file_descriptor, temp_name = tempfile.mkstemp(dir=cache_folder, prefix="mmap.")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as cache_file:
                self._write_cache_file(cache_file)

            if platform.system() == "Windows":
                # Memory map does not work on Windows for some reason
                # Use a simple string as a fallback
                self._data = temp_path.read_text(encoding="utf-8")
            else:
                with open(temp_path, "r+b") as cache_file:
                    if os.fstat(cache_file.fileno()).st_size > 0:
                        # mmap() cannot map a zero-length file
                        self._data = mmap.mmap(cache_file.fileno(), 0)
        except BaseException:
            self.close()
            raise
        finally:
            # The data lives in the mapping (or in memory) from here on
            temp_path.unlink(missing_ok=True)

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self):
        """Release the mapping. Only call once no reader can use it any more."""
        if self._closed:
            return
        self._closed = True
        data, self._data = self._data, b""
        if isinstance(data, mmap.mmap):
            try:
                data.close()
            except BufferError:
                # A reader still exports the buffer; the mapping is freed when
                # that last reference goes away
                logger.debug("ripgrep mapping still exported; deferring release")

    def as_input(self):
        # subprocess only closes stdin for falsy input, so an empty cache
        # must be passed as "" instead of the empty buffer, otherwise rg
        # waits forever
        if not self._data:
            return ""

        return self._data


def map_global_line_to_file(cumulative: list[int], global_line: int) -> tuple[int, int]:
    index = bisect.bisect_left(cumulative, global_line)
    start = cumulative[index - 1] if index > 0 else 0
    return index, global_line - start


def run_ripgrep(cache_input, terms: list[str], max_count: int) -> list[tuple[int, str]]:
    # Before the emptiness check, so text input is compared as bytes
    if isinstance(cache_input, str):
        cache_input = cache_input.encode("utf-8")
    if not cache_input or not terms:
        return []
    terms = [term for term in terms if "\n" not in term]
    if not terms:
        return []

    def build_cmd(with_fixed_strings: bool):
        cmd = [
            "rg",
            "--no-config",
            # One NUL byte anywhere in the cache would otherwise make ripgrep
            # treat the whole input as binary and print no matching lines
            "--text",
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
    config = get_config_values(Path(repository.path))
    max_vector_distance = config["server"]["chroma"]["maxVectorDistance"]

    def build_state(snapshot: RepositorySnapshot) -> RipGrepCache:
        """Build a complete replacement index; the caller publishes it."""
        return RipGrepCache(repository, snapshot)

    def _fetch(
        query_text: str, limit: int, cache: RipGrepCache, snapshot: RepositorySnapshot
    ):
        terms = query_terms(query_text)
        query_text = " ".join(terms)
        files = {}

        # (path, line number, distinct query words) in ripgrep's order
        matches = []
        for global_line, line_text in run_ripgrep(
            cache.as_input(), terms, RIPGREP_MAX_CANDIDATES
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
                    _count_distinct_matched_words(line_text, terms),
                )
            )

        # Keep the limit best lines overall: most distinct query words first;
        # the sort is stable, so ties keep ripgrep's order (important files
        # first)
        matches.sort(key=lambda match: -match[2])
        for relative_path, line_number, distinct_words in matches[:limit]:
            if relative_path not in files:
                files[relative_path] = Result(
                    query_text, snapshot.get_file(relative_path)
                )
            # A regex word (e.g. "[0-9]{2,10}") never appears literally; count
            # it as one word. This keeps ripgrep results on comparable levels
            # with chroma results.
            files[relative_path].add_line(
                line_number, max_vector_distance * 0.8 / max(distinct_words, 1)
            )

        return list(files.values())

    def fetch_in_snapshot(query_text: str, limit: int, query_snapshot):
        """Fetch using the index that belongs to the query's snapshot"""
        cache = query_snapshot.state_for(source)
        return _fetch(query_text, limit, cache, query_snapshot.repository)

    # Standalone use (no Engine): the source publishes its own index. Readers
    # lease it so a rebuild only closes it after the last reader is done.
    standalone_lock = threading.Lock()
    standalone: list[QuerySnapshot] = []

    def cache_repo():
        # Index the repository's currently published snapshot
        snapshot = repository.snapshot
        replacement = QuerySnapshot(snapshot, {id(source): build_state(snapshot)})
        with standalone_lock:
            previous = standalone[:]
            standalone[:] = [replacement]
        for retired in previous:
            retired.release()

    def lease_current() -> QuerySnapshot | None:
        with standalone_lock:
            return standalone[0].acquire() if standalone else None

    def fetch(query_text: str, limit: int):
        while (leased := lease_current()) is None:
            repository.analyze_files()
            cache_repo()

        with leased:
            return fetch_in_snapshot(query_text, limit, leased)

    source = {
        "fetch": fetch,
        "fetch_in_snapshot": fetch_in_snapshot,
        "build_state": build_state,
        "cache_repo": cache_repo,
    }
    return source
