"""
    This module allows you to use Codector as a library
"""

from typing import Dict, List
import time

from git.repo import Repo


class File:
    def __init__(self, path: str):
        self.path = path
        self.score = 0.0
        self.commit_messages = set()

    def increment_score(self, amount: float):
        self.score += amount

    def add_commit_message(self, message: str):
        self.commit_messages.add(message)


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

    def version(self):
        """
        Returns the version of the library
        """
        return "0.1.0"

    def is_ready(self):
        """
        Returns true if the library is ready
        """
        return False

    def analyze_files(self):
        self._file_data = {}

        all_commits = {}

        for branch in self.repo.branches:
            for commit in self.repo.iter_commits(branch):
                all_commits[commit.hexsha] = commit

        for commit in all_commits.values():
            for path in commit.stats.files:
                if path not in self._file_data:
                    self._file_data[path] = File(path)
                self._file_data[path].add_commit_message(commit.message)
                current_time = int(time.time())
                age_of_commit_in_seconds = current_time - commit.committed_date
                age_of_commit_in_days = int(age_of_commit_in_seconds / 86400)
                self._file_data[path].increment_score(
                    100 / (age_of_commit_in_days**2)
                )

        self._sorted_files = list(
            sorted(
                self._file_data.keys(),
                key=lambda x: self._file_data[x].score,
                reverse=True,
            )
        )

    def top_files(self):
        return [self._file_data[path] for path in self._sorted_files]
