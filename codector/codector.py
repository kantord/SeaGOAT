"""
    This module allows you to use Codector as a library
"""

from typing import Dict, List
from pathlib import Path
import hashlib
import pickle

from git.repo import Repo
from gitdb.db.loose import os
from tqdm import tqdm
import appdirs

from codector.file import File


IGNORED_BRANCHES = {"gh-pages"}
CACHE_FORMAT_VERSION = 1


class Codector:
    """
    A search engine for a code repository
    """

    def __init__(self, path: str):
        """
        Initializes the library
        """
        self.path = path
        self.repo = Repo(path)
        self._sorted_files: List[str] = []
        self._file_data: Dict[str, File] = {}
        self._commits_already_analyzed = set()
        cache_root = self._get_cache_root()
        self.cache_folder = cache_root / self._get_project_hash()
        self.cache_folder.mkdir(parents=True, exist_ok=True)
        self._load_cache()

    def _get_cache_root(self):
        return Path(
            appdirs.user_cache_dir(
                "codector-pytest" if "PYTEST_CURRENT_TEST" in os.environ else "codector"
            )
        )

    def _load_cache(self):
        try:
            with open(self.cache_folder / "commits", "rb") as commits_file:
                self._commits_already_analyzed = pickle.load(commits_file)
            with open(self.cache_folder / "file_data", "rb") as file_data_file:
                self._file_data = pickle.load(file_data_file)
            with open(self.cache_folder / "sorted_files", "rb") as sorted_files_file:
                self._sorted_files = pickle.load(sorted_files_file)
        except FileNotFoundError:
            print("Cache not found, need to analyze files")

    def _write_cache(self):
        with open(self.cache_folder / "commits", "wb") as commits_file:
            pickle.dump(self._commits_already_analyzed, commits_file)
        with open(self.cache_folder / "file_data", "wb") as file_data_file:
            pickle.dump(self._file_data, file_data_file)
        with open(self.cache_folder / "sorted_files", "wb") as sorted_files_file:
            pickle.dump(self._sorted_files, sorted_files_file)

    def _get_project_hash(self):
        normalized_path = Path(self.path).expanduser().resolve()
        text = f"""
        Cache version: {CACHE_FORMAT_VERSION}
        Normalized path: {normalized_path}
        """

        return hashlib.sha256(text.encode()).hexdigest()

    def _get_all_commits(self):
        all_commits = {}

        for branch in tqdm(self.repo.branches, desc="Analyzing branches"):
            if branch.name in IGNORED_BRANCHES:
                continue
            for commit in self.repo.iter_commits(branch):
                all_commits[commit.hexsha] = commit

        return all_commits.values()

    def _sort_files(self):
        self._sorted_files = list(
            sorted(
                self._file_data.keys(),
                key=lambda x: self._file_data[x].score,
                reverse=True,
            )
        )

    def analyze_files(self):
        for commit in tqdm(self._get_all_commits(), desc="Analyzing commits"):
            if commit.hexsha in self._commits_already_analyzed:
                continue
            self._commits_already_analyzed.add(commit.hexsha)
            for path in commit.stats.files:
                if path not in self._file_data:
                    self._file_data[path] = File(path)
                self._file_data[path].add_commit(commit)

        self._sort_files()
        self._write_cache()

    def top_files(self):
        return [self._file_data[path] for path in self._sorted_files]

    def get_file(self, path: str):
        if path not in self._file_data:
            raise RuntimeError("File not found or not analyzed yet")
        return self._file_data[path]
