"""
    This module allows you to use Codector as a library
"""

from typing import Dict, List

from git.repo import Repo
from tqdm import tqdm

from codector.file import File


IGNORED_BRANCHES = {"gh-pages"}


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
        self._file_data = {}

        for commit in tqdm(self._get_all_commits(), desc="Analyzing commits"):
            if commit.hexsha in self._commits_already_analyzed:
                continue
            self._commits_already_analyzed.add(commit.hexsha)
            for path in commit.stats.files:
                if path not in self._file_data:
                    self._file_data[path] = File(path)
                self._file_data[path].add_commit(commit)

        self._sort_files()

    def top_files(self):
        return [self._file_data[path] for path in self._sorted_files]

    def get_file(self, path: str):
        if path not in self._file_data:
            raise RuntimeError("File not found or not analyzed yet")
        return self._file_data[path]
