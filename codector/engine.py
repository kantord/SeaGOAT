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
CACHE_FORMAT_VERSION = 3


class Engine:
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
        self._commits = {}
        self._last_analyzed_version_of_branch = {}
        self._load_cache()

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
                    self._commits,
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
                self._commits,
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
            if self._last_analyzed_version_of_branch.get(branch.name) == branch.commit:
                continue
            for commit in self.repo.iter_commits(branch):
                self._commits[commit.hexsha] = commit
            self._last_analyzed_version_of_branch[branch.name] = branch.commit

        return self._commits.values()

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
