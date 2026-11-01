"""
This module allows you to use seagoat as a library
"""

import asyncio
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
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
    chunks_already_analyzed: set[str]
    chunks_not_yet_analyzed: set[str]


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
                "chunks_already_analyzed": set(),
                "chunks_not_yet_analyzed": set(),
            },
        )
        self.cache.load()
        self.repository = Repository(path)
        self.config = get_config_values(Path(path))
        # Startup reconciliation of durable analyzed marks against the real
        # vector store happens at most once per Engine instance.
        self._repair_done = False

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

        return chunks_to_process[minimum_chunks_to_analyze:]

    def plan_indexing(self, excluded_ids=frozenset()):
        """Plan pending indexing work without embedding anything.

        Analyzes repository metadata, refreshes source caches, reconciles
        legacy "analyzed" marks against the real vector store and returns the
        pending FileChunks in ranking order. In-memory failed chunk IDs are
        excluded from both the returned chunks and the pending-ID set.
        """
        excluded = frozenset(excluded_ids)
        self.repository.analyze_files()

        for fetcher in self._fetchers["async"] + self._fetchers["sync"]:
            fetcher["cache_repo"]()

        current_chunks = [
            chunk
            for file, _ in self.repository.top_files()
            for chunk in file.get_chunks()
        ]
        self._reconcile_legacy_marks({chunk.chunk_id for chunk in current_chunks})
        chunks_to_process = [
            chunk
            for chunk in current_chunks
            if chunk.chunk_id not in self.cache.data["chunks_already_analyzed"]
            and chunk.chunk_id not in excluded
        ]
        self.cache.data["chunks_not_yet_analyzed"].difference_update(excluded)
        self.cache.data["chunks_not_yet_analyzed"].update(
            chunk.chunk_id for chunk in chunks_to_process
        )
        return chunks_to_process

    def _reconcile_legacy_marks(self, current_ids):
        """Re-queue IDs the old cache marked analyzed but Chroma never stored.

        Runs once per Engine, after a successful repository read. A failed
        Chroma read propagates and leaves repair pending for the next pass.
        """
        if self._repair_done:
            return
        marked_ids = set(self.cache.data["chunks_already_analyzed"])
        if marked_ids:
            indexed_ids = self._query_indexed_ids(marked_ids)
            missing = marked_ids - indexed_ids
            if missing:
                self.cache.data["chunks_already_analyzed"].difference_update(missing)
                self.cache.data["chunks_not_yet_analyzed"].update(missing & current_ids)
                self.cache.persist()
        self._repair_done = True

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
        """The only completion path: embed/upsert a batch, then persist once.

        Only after the whole batch reaches storage do IDs move from pending
        to analyzed. Duplicate already-indexed tasks are filtered safely.
        """
        chunks = [
            chunk
            for chunk in chunks
            if chunk.chunk_id not in self.cache.data["chunks_already_analyzed"]
        ]
        if not chunks:
            return

        self._add_batch_to_collection(chunks)

        ids = {chunk.chunk_id for chunk in chunks}
        pending = self.cache.data["chunks_not_yet_analyzed"]
        previously_pending = pending & ids
        self.cache.data["chunks_already_analyzed"].update(ids)
        pending.difference_update(ids)
        try:
            self.cache.persist()
        except Exception:
            # Upsert is idempotent: preserve retryable in-memory bookkeeping
            # when persisting the completion record fails after storage succeeds.
            self.cache.data["chunks_already_analyzed"].difference_update(ids)
            pending.update(previously_pending)
            raise

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
