"""
This module allows you to use seagoat as a library
"""

import asyncio
from collections import deque
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from itertools import chain, islice
from pathlib import Path
from typing import TypedDict

from tqdm import tqdm

from seagoat.cache import Cache
from seagoat.gitfile import GitFile
from seagoat.repository import Repository
from seagoat.result import get_best_score
from seagoat.sources import chroma, ripgrep
from seagoat.utils.config import get_config_values


class RepositoryData(TypedDict):
    last_analyzed_version_of_branch: dict[str, str]
    required_commits: set[str]
    commits_already_analyzed: set[str]
    file_data: dict[str, GitFile]
    sorted_files: list[str]


class Engine:
    """
    A search engine for a code repository
    """

    def __init__(self, path: str):
        """
        Initializes the library
        """
        self.path = path
        self._results = []
        self.cache = Cache[RepositoryData](
            "cache",
            Path(path),
            {
                "last_analyzed_version_of_branch": {},
                "required_commits": set(),
                "commits_already_analyzed": set(),
                "file_data": {},
                "sorted_files": [],
            },
        )
        self.cache.load()
        # Old cache files carried per-batch chunk ID sets; those are ignored
        # (Chroma is the durable record now) and stripped so they are never
        # persisted again, without bumping the cache format.
        self.cache.data.pop("chunks_already_analyzed", None)
        self.cache.data.pop("chunks_not_yet_analyzed", None)
        self.repository = Repository(path)
        self.config = get_config_values(Path(path))
        # In-memory (never persisted) snapshot of the last plan: which chunks
        # are current, which are pending and which are known indexed. Stats
        # stay cheap; Chroma remains the only durable indexing record.
        self._current_ids: set[str] = set()
        self._pending_ids: set[str] = set()
        self._indexed_ids: set[str] = set()
        # Stale Chroma row IDs to prune, snapshot at plan time so deletions
        # never skip rows while earlier pages are removed.
        self._stale_candidates: deque[str] = deque()
        # Repository status pinned when the current plan was built; pruning
        # re-validates against it so a HEAD move cannot authorize deletion.
        self._plan_repo_hash: str | None = None

        self._fetchers = {
            "async": [
                ripgrep.initialize(self.repository),
            ],
            "sync": [
                chroma.initialize(self.repository),
            ],
        }

    def analyze_codebase(self, minimum_chunks_to_analyze=None):
        """Synchronous compatibility wrapper around the batch pipeline.

        Plans all pending chunks, then embeds the requested number of them
        (or the historical default quota) through :meth:`process_batch`,
        honoring explicit minimums exactly and processing the final partial
        batch.
        """
        chunks_to_process = self.plan_indexing()

        if minimum_chunks_to_analyze is None:
            min_value = self.config["server"]["engine"]["minChunksToAnalyze"][
                "minValue"
            ]
            percentage = self.config["server"]["engine"]["minChunksToAnalyze"][
                "percentage"
            ]
            minimum_chunks_to_analyze = min(
                max(min_value, int(len(chunks_to_process) * percentage)),
                len(chunks_to_process),
            )
        else:
            minimum_chunks_to_analyze = min(
                minimum_chunks_to_analyze, len(chunks_to_process)
            )

        batch_size = self.config["server"]["chroma"]["batchSize"]
        chunks_to_analyze = chunks_to_process[:minimum_chunks_to_analyze]
        for start in tqdm(
            range(0, len(chunks_to_analyze), batch_size),
            desc="Analyzing source code",
        ):
            batch = chunks_to_analyze[start : start + batch_size]
            self.process_batch(batch)

        # Direct synchronous callers get the same safe cleanup as the queue:
        # prune stale Chroma rows against the still-valid completed plan.
        while self.pending_prune_count():
            self.prune_stale()

        return chunks_to_process[minimum_chunks_to_analyze:]

    def plan_indexing(self, excluded_ids=frozenset()):
        """Plan pending indexing work without embedding anything.

        Chroma is the authoritative durable record: after a complete
        successful repository scan, current chunks are planned from the real
        vector store. Legacy "analyzed" pickle marks have no effect anymore;
        existing vector presence makes marked-but-missing repair automatic.
        In-memory failed chunk IDs are excluded from the pending plan.
        """
        excluded = frozenset(excluded_ids)
        # A failed later scan must revoke the previous plan's permission to
        # delete, even if its repository hash still happens to match.
        self._plan_repo_hash = None
        self._stale_candidates.clear()
        plan_hash = self.repository.get_status_hash()
        self.repository.analyze_files()

        for fetcher in self._fetchers["async"] + self._fetchers["sync"]:
            fetcher["cache_repo"]()

        # GitFile materialization reads HEAD again, so pin the full repository
        # status before materializing and re-validate it afterwards; a HEAD
        # move in this gap must not authorize pruning from a mixed plan.
        current_chunks = [
            chunk
            for file, _ in self.repository.top_files()
            for chunk in file.get_chunks()
        ]
        if self.repository.get_status_hash() != plan_hash:
            raise RuntimeError(
                "repository changed while materializing chunks; "
                "refusing to plan from a mixed snapshot"
            )

        current_ids = {chunk.chunk_id for chunk in current_chunks}
        indexed_ids = self._query_indexed_ids(current_ids)

        # Enumerate every stored row (bounded pages), then snapshot the stale
        # candidates in a stable list so deletions never skip rows.
        # An empty current plan never authorizes deletion, including a valid
        # empty/unborn repository. Read failures propagate rather than becoming
        # a successful empty collection.
        stale_candidates = (
            self._all_indexed_ids() - current_ids if current_ids else set()
        )
        if self.repository.get_status_hash() != plan_hash:
            raise RuntimeError("repository changed while reading the vector index")

        # Persist metadata before publishing the completed indexing snapshot.
        # Chunk completion never writes this cache.
        self.cache.persist()

        self._current_ids = current_ids
        self._indexed_ids = indexed_ids & current_ids
        self._pending_ids = (current_ids - self._indexed_ids) - excluded
        self._stale_candidates = deque(sorted(stale_candidates))
        self._plan_repo_hash = plan_hash if current_ids else None

        ordered = []
        seen = set()
        for chunk in current_chunks:
            if chunk.chunk_id in self._pending_ids and chunk.chunk_id not in seen:
                ordered.append(chunk)
                seen.add(chunk.chunk_id)
        return ordered

    def _query_indexed_ids(self, ids: set[str]) -> set[str]:
        """Ask the real (sync) sources which of the given IDs are indexed."""
        indexed: set[str] = set()
        for source in self._fetchers["sync"]:
            indexed.update(source["indexed_ids"](list(ids)))
        return indexed

    def probe_embedding(self):
        """Check embedding availability without writing vectors."""
        for source in self._fetchers["sync"]:
            if source.get("probe_embedding") is not None:
                source["probe_embedding"]()

    def process_batch(self, chunks):
        """The only completion path: embed/upsert a batch into Chroma.

        Completion/statistics only change after a successful upsert; nothing
        (and no per-batch pickle write) happens before storage. Duplicate
        already-indexed tasks are filtered safely. Failed/retained/queued
        work stays pending. Chroma is the only durable indexing record.
        """
        chunks = [chunk for chunk in chunks if chunk.chunk_id not in self._indexed_ids]
        if not chunks:
            return

        self._add_batch_to_collection(chunks)

        ids = {chunk.chunk_id for chunk in chunks}
        # Bookkeeping is in-memory only, and only after storage succeeded.
        self._indexed_ids.update(ids & self._current_ids)
        self._pending_ids.difference_update(ids)

    def get_indexing_stats(self, failed_ids=frozenset()):
        """Cheap in-memory indexed/pending/current counters for the UI."""
        return {
            "analyzed": len(self._indexed_ids),
            "pending": len(self._pending_ids),
            "total": len(self._current_ids),
            "failed": len(self._current_ids & failed_ids),
        }

    def filter_pending(self, chunks):
        """Return only chunks not yet known to be present in Chroma."""
        return [chunk for chunk in chunks if chunk.chunk_id not in self._indexed_ids]

    def discard_pending(self, ids):
        """Remove failed IDs from pending stats (quarantine is process-local)."""
        self._pending_ids.difference_update(ids)

    def pending_prune_count(self):
        """How many stale Chroma rows the current plan wants to delete."""
        return len(self._stale_candidates)

    def prune_stale(self, limit=1000):
        """Delete up to ``limit`` stale Chroma rows, in bounded pages.

        Safe cleanup for direct synchronous callers too. Deletion only runs
        against a still-valid completed plan; any repository change or
        storage error aborts and keeps the candidates for retry.
        """
        if limit <= 0:
            raise ValueError("prune limit must be positive")
        if (
            not self._current_ids
            or not self._stale_candidates
            or self._plan_repo_hash is None
        ):
            return 0
        if self.repository.get_status_hash() != self._plan_repo_hash:
            self._stale_candidates.clear()
            self._plan_repo_hash = None
            raise RuntimeError(
                "repository changed since planning; refusing to prune stale rows"
            )
        to_delete = list(islice(self._stale_candidates, min(limit, 1000)))
        # Keep candidates until storage succeeds. Retrying a partly successful
        # deletion is safe because Chroma deletes by ID idempotently.
        self._delete_indexed_ids(to_delete)
        for _ in to_delete:
            self._stale_candidates.popleft()
        return len(to_delete)

    def _delete_indexed_ids(self, ids):
        for source in self._fetchers["sync"]:
            delete_ids = source.get("delete_ids")
            if delete_ids is not None:
                delete_ids(list(ids))

    def _all_indexed_ids(self) -> set[str]:
        """Enumerate every stored row ID across sync sources (bounded pages)."""
        all_ids: set[str] = set()
        for source in self._fetchers["sync"]:
            all_ids.update(source["all_ids"]())
        return all_ids

    def process_chunk(self, chunk):
        """Single-element compatibility wrapper around process_batch."""
        self.process_batch([chunk])

    def _add_batch_to_collection(self, chunks):
        for source in chain(*self._fetchers.values()):
            cache_batch = source.get("cache_batch")
            if cache_batch is not None:
                cache_batch(chunks)
            elif source.get("cache_chunk") is not None:
                for chunk in chunks:
                    source["cache_chunk"](chunk)

    def query_sync(self, query: str, limit_clue=50, context_above=0, context_below=0):
        """
        limit_clue: a clue regarding how many results will be processed in the end

        Sources don't need to respect this value and it does not have an inherent
        direct effect on the number of results returned, but sources can use it as
        a rule of thumb.
        """

        self._results = []
        max_workers = self.config["server"]["engine"]["maxWorkers"]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(source["fetch"], query, limit_clue)
                for source in self._fetchers["async"]
            ]

            for source in self._fetchers["sync"]:
                self._results.extend(source["fetch"](query, limit_clue))

            for future in futures:
                self._results.extend(future.result())

        self._include_context_lines(context_above, context_below)

        return self._format_results(query, limit_clue)

    async def query(self, *args, **kwargs):
        return await asyncio.to_thread(self.query_sync, *args, **kwargs)

    def _include_context_lines(self, context_above: int, context_below: int):
        for result in self._results:
            result.add_context_lines(-context_above)
            result.add_context_lines(context_below)

    def _get_normalization_function(
        self, values: Iterable[float], min_=None, max_=None
    ) -> Callable[[float], float]:
        if not values:
            return lambda x: 0

        max_value = max_ or max(values)
        min_value = min_ or min(values)

        def normalize(value: float) -> float:
            if max_value != min_value:
                return (value - min_value) / (max_value - min_value)

            return 1

        return normalize

    def _format_results(self, query: str, hard_count_limit: int = 1000):
        merged_results = {}

        for result_item in self._results:
            if result_item.gitfile.path not in merged_results:
                merged_results[result_item.gitfile.path] = result_item
                continue

            merged_results[result_item.gitfile.path].extend(result_item)

        results_to_sort = list(merged_results.values())

        scores = [get_best_score(x) for x in results_to_sort]

        if not scores:
            return []

        top_files = {
            file.path: 0.0 - position_score
            for file, position_score in self.repository.top_files()
        }

        normalize_score = self._get_normalization_function(scores, min_=0.0)
        normalize_file_position = self._get_normalization_function(top_files.values())

        def get_file_position(path: str):
            normalized_path = Path(path).as_posix()

            if normalized_path not in top_files:
                return 0

            return top_files[normalized_path]

        return sorted(
            results_to_sort,
            key=lambda x: (
                0.7 * normalize_score(get_best_score(x))
                + 0.3 * normalize_file_position(get_file_position(x.gitfile.path))
            ),
        )[:hard_count_limit]
