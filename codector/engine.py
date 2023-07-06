"""
    This module allows you to use Codector as a library
"""

from pathlib import Path
import hashlib
from typing import Dict, List, Set
from typing_extensions import TypedDict

from tqdm import tqdm
from gitdb.db.loose import os
import appdirs
import chromadb

from chromadb.errors import IDAlreadyExistsError
from codector.cache import Cache
from codector.repository import Repository
from codector.result import Result
from codector.file import File
from codector.sources import ripgrep

CACHE_FORMAT_VERSION = 15


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


# pylint: disable=too-many-instance-attributes
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

        self._chroma_client = chromadb.Client(
            chromadb.Settings(
                chroma_db_impl="duckdb+parquet",
                persist_directory=str(self._get_cache_folder()),
                anonymized_telemetry=False,
            )
        )
        self._chroma_collection = self._chroma_client.get_or_create_collection(
            name="code_data"
        )
        self._cache = Cache[RepositoryData](
            self._get_cache_folder() / "cache",
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
        self.repository = Repository(path, self._cache)
        self._fetchers = [
            ripgrep.initialize(self.repository),
        ]

    def _get_cache_folder(self):
        cache_folder = self._get_cache_root() / self._get_project_hash()
        cache_folder.mkdir(parents=True, exist_ok=True)

        return cache_folder

    def _get_cache_root(self):
        return Path(
            appdirs.user_cache_dir(
                "codector-pytest" if "PYTEST_CURRENT_TEST" in os.environ else "codector"
            )
        )

    def _get_project_hash(self):
        normalized_path = Path(self.path).expanduser().resolve()
        text = f"""
        Cache version: {CACHE_FORMAT_VERSION}
        Normalized path: {normalized_path}
        """

        return hashlib.sha256(text.encode()).hexdigest()

    def analyze_codebase(self):
        self.repository.analyze_files()
        self._create_vector_embeddings()

    def _add_to_collection(self, chunk):
        try:
            self._chroma_collection.add(
                ids=[chunk.chunk_id],
                documents=[chunk.chunk],
                metadatas=[{"path": chunk.path, "line": chunk.codeline}],
            )
        except IDAlreadyExistsError:
            pass

    def _create_vector_embeddings(self):
        chunks_to_process = []
        minimum_files_to_analyze = max(40, int(len(self.repository.top_files()) * 0.2))
        for file in self.repository.top_files()[:minimum_files_to_analyze]:
            for chunk in file.get_chunks():
                chunks_to_process.append(chunk)

        for chunk in tqdm(chunks_to_process, desc="Analyzing source code"):
            if chunk.chunk_id in self._cache.data["chunks_already_analyzed"]:
                continue

            self._add_to_collection(chunk)
            self._cache.data["chunks_already_analyzed"].add(chunk.chunk_id)

        self._cache.persist()
        self._chroma_client.persist()

    def query(self, query: str):
        self.query_string = query

    def _fetch_from_chromadb(self):
        chromadb_results = [
            self._chroma_collection.query(query_texts=[self.query_string], n_results=50)
        ]
        self._results_from_chromadb = (
            list(
                zip(
                    chromadb_results[0]["metadatas"][0],
                    chromadb_results[0]["distances"][0],
                )
            )
            if chromadb_results[0]["metadatas"] and chromadb_results[0]["distances"]
            else None
        ) or []

    def fetch(self):
        self._results = []
        self._fetch_from_chromadb()
        for fetch_source in self._fetchers:
            self._results.extend(fetch_source(self.query_string))

    def get_results(self):
        path_order = []
        formatted_results = {}

        for metadata, distance in self._results_from_chromadb:
            path = str(metadata["path"])
            line = int(metadata["line"])
            if path not in path_order:
                path_order.append(path)

            if path not in formatted_results:
                formatted_results[path] = Result(path, Path(self.path) / path)
            formatted_results[path].add_line(line, distance)

        for item in self._results:
            relative_path = str(item["relative_path"])
            absolute_path = item["absolute_path"]
            line_number = item["line_number"]

            if relative_path not in path_order:
                path_order.append(relative_path)
                formatted_results[relative_path] = Result(
                    str(relative_path), absolute_path
                )
            formatted_results[relative_path].add_line(line_number, 0.0)

        return [formatted_results[path] for path in path_order]
