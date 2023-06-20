"""
    This module allows you to use Codector as a library
"""

from collections import defaultdict
from typing import DefaultDict

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
            files_in_commit = set()
            for item in commit.diff():
                for path in tuple(set((item.a_path, item.b_path))):
                    if path:
                        files_in_commit.add(path)
            for files in files_in_commit:
                found_files[files] += 1

        return sorted(found_files.keys(), key=lambda x: found_files[x], reverse=True)
