"""
    This module allows you to use Codector as a library
"""


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
        return {item.path for item in self.repo.tree()}
