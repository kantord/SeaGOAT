"""
    This module allows you to use Codector as a library
"""

from typing import Dict, List, Set
from pathlib import Path
import hashlib
import pickle

from git.repo import Repo
from gitdb.db.loose import os
from tqdm import tqdm
import appdirs
import chromadb
from chromadb.errors import IDAlreadyExistsError

from codector.file import File
from codector.result import Result


IGNORED_BRANCHES = {"gh-pages"}
CACHE_FORMAT_VERSION = 9
SUPPORTED_FILE_TYPES = {
    ".txt",
    ".md",
    ".py",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".html",
}


class Engine:
    """
    A search engine for a code repository
    """

    # pylint: disable=too-many-instance-attributes
    def __init__(self, path: str):
        """
        Initializes the library
        """
        self.path = path
        self.repo = Repo(path)
        self._sorted_files: List[str] = []
        self._file_data: Dict[str, File] = {}
        self._commits_already_analyzed: Set[str] = set()
        self._required_commits: Set[str] = set()
        self._last_analyzed_version_of_branch: Dict[str, str] = {}
        self._load_cache()
        self.query_string = ""
        self._results = []
        self._chroma_client = chromadb.Client()
        self._chroma_collection = self._chroma_client.create_collection(
            name="code_data"
        )

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

    def _load_cache(self):
        try:
            with open(self._get_cache_folder() / "cache", "rb") as cache_file:
                cache_tuple = pickle.load(cache_file)
                (
                    self._commits_already_analyzed,
                    self._file_data,
                    self._sorted_files,
                    self._required_commits,
                    self._last_analyzed_version_of_branch,
                ) = cache_tuple
        except (FileNotFoundError, pickle.UnpicklingError, EOFError):
            print("Cache not found, need to analyze files")

    def _write_cache(self):
        with open(self._get_cache_folder() / "cache", "wb") as cache_file:
            cache_tuple = (
                self._commits_already_analyzed,
                self._file_data,
                self._sorted_files,
                self._required_commits,
                self._last_analyzed_version_of_branch,
            )
            pickle.dump(cache_tuple, cache_file)

    def _get_project_hash(self):
        normalized_path = Path(self.path).expanduser().resolve()
        text = f"""
        Cache version: {CACHE_FORMAT_VERSION}
        Normalized path: {normalized_path}
        """

        return hashlib.sha256(text.encode()).hexdigest()

    def _get_all_commits(self):
        for branch in tqdm(self.repo.branches, desc="Analyzing branches"):
            if branch.name in IGNORED_BRANCHES:
                continue
            if (
                self._last_analyzed_version_of_branch.get(branch.name)
                == branch.commit.hexsha
            ):
                continue
            for commit in self.repo.iter_commits(branch):
                self._required_commits.add(commit.hexsha)
            self._last_analyzed_version_of_branch[branch.name] = branch.commit.hexsha

        return (self.repo.commit(commit) for commit in self._required_commits)

    def _sort_files(self):
        self._sorted_files = list(
            sorted(
                self._file_data.keys(),
                key=lambda x: self._file_data[x].get_score(),
                reverse=True,
            )
        )

    def analyze_files(self):
        for commit in tqdm(
            self._get_all_commits(),
            desc="Analyzing commits",
            total=len(self._required_commits),
        ):
            if commit.hexsha in self._commits_already_analyzed:
                continue
            self._commits_already_analyzed.add(commit.hexsha)
            for path in commit.stats.files:  # type: ignore[reportGeneralTypeIssues]
                if Path(path).suffix not in SUPPORTED_FILE_TYPES:
                    continue
                if path not in self._file_data:
                    self._file_data[path] = File(path)
                self._file_data[path].add_commit(commit)

        self._sort_files()
        self._write_cache()
        self._create_vector_embeddings()

    def _create_vector_embeddings(self):
        for file in self._file_data.values():
            full_path = Path(self.path) / file.path
            if not full_path.exists():
                continue
            with open(full_path, "r", encoding="utf-8") as source_code_file:
                file_content = source_code_file.read()

            content = f"""
                {file_content}
                ###
                {file.get_metadata()}
            """
            try:
                self._chroma_collection.add(
                    ids=[file.path],
                    documents=[content],
                    metadatas=[{"path": file.path}],
                )
            except IDAlreadyExistsError:
                pass

    def top_files(self):
        return [self._file_data[path] for path in self._sorted_files]

    def get_file(self, path: str):
        if path not in self._file_data:
            raise RuntimeError("File not found or not analyzed yet")
        return self._file_data[path]

    def query(self, query: str):
        self.query_string = query

    def fetch(self):
        chromadb_results = [
            self._chroma_collection.query(query_texts=[self.query_string], n_results=5)
        ]
        metadatas = (
            chromadb_results[0]["metadatas"][0]
            if chromadb_results[0]["metadatas"]
            else None
        )

        self._results = [str(item["path"]) for item in metadatas] if metadatas else []

    def get_results(self):
        return [Result(path) for path in self._results]
