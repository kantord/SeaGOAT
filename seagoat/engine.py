"""
This module allows you to use seagoat as a library
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from itertools import chain
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Set

import nest_asyncio
from tqdm import tqdm
from typing_extensions import TypedDict

from seagoat.cache import Cache
from seagoat.gitfile import GitFile
from seagoat.repository import Repository
from seagoat.result import get_best_score
from seagoat.sources import chroma, ripgrep
from seagoat.utils.config import get_config_values


class RepositoryData(TypedDict):
    last_analyzed_version_of_branch: Dict[str, str]
    required_commits: Set[str]
    commits_already_analyzed: Set[str]
    file_data: Dict[str, GitFile]
    sorted_files: List[str]
    chunks_already_analyzed: Set[str]
    chunks_not_yet_analyzed: Set[str]


nest_asyncio.apply()


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

        self._fetchers = {
            "async": [
                ripgrep.initialize(self.repository),
            ],
            "sync": [
                chroma.initialize(self.repository),
            ],
        }

    def analyze_codebase(self, minimum_chunks_to_analyze=None):
        self.repository.analyze_files()

        for fetcher in self._fetchers["async"] + self._fetchers["sync"]:
            fetcher["cache_repo"]()

        return self._create_vector_embeddings(minimum_chunks_to_analyze)

    def _add_to_collection(self, chunk):
        for source in chain(*self._fetchers.values()):
            source["cache_chunk"](chunk)

    def process_chunk(self, chunk):
        if chunk.chunk_id in self.cache.data["chunks_already_analyzed"]:
            return

        self._add_to_collection(chunk)
        self.cache.data["chunks_already_analyzed"].add(chunk.chunk_id)

        if chunk.chunk_id in self.cache.data["chunks_not_yet_analyzed"]:
            self.cache.data["chunks_not_yet_analyzed"].remove(chunk.chunk_id)

        self.cache.persist()

    def _create_vector_embeddings(self, minimum_chunks_to_analyze=None):
        chunks_to_process = []

        for file, _ in self.repository.top_files():
            for chunk in file.get_chunks():
                if chunk.chunk_id not in self.cache.data["chunks_already_analyzed"]:
                    chunks_to_process.append(chunk)
                    self.cache.data["chunks_not_yet_analyzed"].add(chunk.chunk_id)

        if minimum_chunks_to_analyze is None:
            minimum_chunks_to_analyze = min(
                max(40, int(len(chunks_to_process) * 0.2)),
                len(chunks_to_process),
            )

        for _ in tqdm(
            enumerate(range(minimum_chunks_to_analyze)),
            desc="Analyzing source code",
        ):
            chunk = chunks_to_process.pop(0)
            self.process_chunk(chunk)

        return chunks_to_process

    async def query(self, query: str, limit_clue=50, context_above=0, context_below=0):
        """
        limit_clue: a clue regarding how many results will be processed in the end

        Sources don't need to respect this value and it does not have an inherent
        direct effect on the number of results returned, but sources can use it as
        a rule of thumb.
        """

        self._results = []
        executor = ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_event_loop()
        async_tasks = [
            loop.run_in_executor(
                executor,
                partial(source["fetch"], query, limit_clue),
            )
            for source in self._fetchers["async"]
        ]

        for source in self._fetchers["sync"]:
            self._results.extend(source["fetch"](query, limit_clue))

        results = await asyncio.gather(*async_tasks)

        for result in results:
            self._results.extend(result)

        self._include_context_lines(context_above, context_below)

        return self._format_results(query, limit_clue)

    def _include_context_lines(self, context_above: int, context_below: int):
        for result in self._results:
            result.add_context_lines(-context_above)
            result.add_context_lines(context_below)

    def query_sync(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.query(*args, **kwargs))

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

        return list(
            sorted(
                results_to_sort,
                key=lambda x: (
                    0.7 * normalize_score(get_best_score(x))
                    + 0.3 * normalize_file_position(get_file_position(x.gitfile.path))
                ),
            )
        )[:hard_count_limit]
