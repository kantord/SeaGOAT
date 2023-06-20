"""
    This module allows you to use Codector as a library
"""


class Codector:
    """
    A search engine for a code repository
    """

    def __init__(self, path: str):
        """
        Initializes the library
        """
        self.path = path

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
        return {"file1.md", "file2.py", "file3.py", "file4.js"}
