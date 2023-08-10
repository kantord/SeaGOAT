"""
    This module allows you to use seagoat as a library
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from itertools import chain
from pathlib import Path
from typing import Callable
from typing import Dict
from typing import Iterable
from typing import List
from typing import Set

import nest_asyncio
from tqdm import tqdm
from typing_extensions import TypedDict

from seagoat.cache import Cache
from seagoat.file import File
from seagoat.repository import Repository
from seagoat.sources import chroma
from seagoat.sources import ripgrep


RepositoryData = TypedDict(
    "RepositoryData",
    {
        "last_analyzed_version_of_branch": Dict[str, str],
        "required_commits": Set[str],
        "commits_already_analyzed": Set[str],
        "file_data": Dict[str, File],
        "sorted_files": List[str],
        "chunks_already_analyzed": Set[str],
    },
)


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
        self.query_string = ""
        self._results_from_chromadb = []
        self._results = []
        self._cache = Cache[RepositoryData](
            "cache",
            Path(path),
            {
                "last_analyzed_version_of_branch": {},
                "required_commits": set(),
                "commits_already_analyzed": set(),
                "file_data": {},
                "sorted_files": [],
                "chunks_already_analyzed": set(),
            },
        )
        self._cache.load()
        self.repository = Repository(path)
        self._fetchers = {
            "async": [
                ripgrep.initialize(self.repository),
            ],
            "sync": [
                chroma.initialize(self.repository),
            ],
        }

    def analyze_codebase(self):
        self.repository.analyze_files()
        self._create_vector_embeddings()

    def _add_to_collection(self, chunk):
        for source in chain(*self._fetchers.values()):
            source["cache_chunk"](chunk)

    def _create_vector_embeddings(self):
        chunks_to_process = []
        minimum_files_to_analyze = min(
            max(40, int(len(self.repository.top_files()) * 0.2)),
            len(self.repository.top_files()),
        )
        for file, _ in self.repository.top_files()[:minimum_files_to_analyze]:
            for chunk in file.get_chunks():
                chunks_to_process.append(chunk)
        for chunk in tqdm(chunks_to_process, desc="Analyzing source code"):
            if chunk.chunk_id in self._cache.data["chunks_already_analyzed"]:
                continue

            self._add_to_collection(chunk)
            self._cache.data["chunks_already_analyzed"].add(chunk.chunk_id)

        self._cache.persist()

    def query(self, query: str):
        self.query_string = query

    async def fetch(self, limit_clue=50):
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
                executor, partial(source["fetch"], self.query_string, limit_clue)
            )
            for source in self._fetchers["async"]
        ]

        for source in self._fetchers["sync"]:
            self._results.extend(source["fetch"](self.query_string, limit_clue))

        results = await asyncio.gather(*async_tasks)
        for result in results:
            self._results.extend(result)

    def fetch_sync(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.fetch(*args, **kwargs))

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

    def get_results(self):
        merged_results = {}

        for result_item in self._results:
            if result_item.path not in merged_results:
                merged_results[result_item.path] = result_item
                continue

            merged_results[result_item.path].extend(result_item)

        results_to_sort = list(merged_results.values())

        scores = [x.get_best_score(self.query_string) for x in results_to_sort]

        if not scores:
            return []

        top_files = {
            file.path: 0.0 - position_score
            for file, position_score in self.repository.top_files()
        }

        normalize_score = self._get_normalization_function(scores, min_=0.0)
        normalize_file_position = self._get_normalization_function(top_files.values())

        return list(
            sorted(
                results_to_sort,
                key=lambda x: (
                    0.7 * normalize_score(x.get_best_score(self.query_string))
                    + 0.3 * normalize_file_position(top_files[x.path])
                ),
            )
        )
