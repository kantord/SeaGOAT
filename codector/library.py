"""
    This module allows you to use Codector as a library
"""

from collections import defaultdict
from typing import DefaultDict
import time

from git.repo import Repo


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

    def files(self):
        """
        Returns a set of all the tracked files in the repository
        """
        all_commits = {}

        for branch in self.repo.branches:
            for commit in self.repo.iter_commits(branch):
                all_commits[commit.hexsha] = commit

        found_files: DefaultDict[str, float] = defaultdict(int)

        for commit in all_commits.values():
            for file in commit.stats.files:
                current_time = int(time.time())
                age_of_commit_in_seconds = (
                    current_time - commit.committed_date
                )  # age in seconds
                age_of_commit_in_days = int(age_of_commit_in_seconds / 86400)
                found_files[file] += 100 / (age_of_commit_in_days**2)

        return sorted(found_files.keys(), key=lambda x: found_files[x], reverse=True)
