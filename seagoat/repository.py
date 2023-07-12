from pathlib import Path

from git.repo import Repo
from tqdm import tqdm

from seagoat.cache import Cache
from seagoat.common import IGNORED_BRANCHES
from seagoat.common import SUPPORTED_FILE_TYPES
from seagoat.file import File


class Repository:
    def __init__(self, path: str, cache: Cache) -> None:
        self._repo = Repo(path)
        self._cache = cache
        self.path = path

    def _get_all_commits(self):
        for branch in tqdm(self._repo.branches, desc="Analyzing branches"):
            if branch.name in IGNORED_BRANCHES:
                continue
            if (
                self._cache.data["last_analyzed_version_of_branch"].get(branch.name)
                == branch.commit.hexsha
            ):
                continue
            for commit in self._repo.iter_commits(branch):
                self._cache.data["required_commits"].add(commit.hexsha)
            self._cache.data["last_analyzed_version_of_branch"][
                branch.name
            ] = branch.commit.hexsha

        return (
            self._repo.commit(commit) for commit in self._cache.data["required_commits"]
        )

    def analyze_files(self):
        for commit in tqdm(
            self._get_all_commits(),
            desc="Analyzing commits",
            total=len(self._cache.data["required_commits"]),
        ):
            if commit.hexsha in self._cache.data["commits_already_analyzed"]:
                continue
            self._cache.data["commits_already_analyzed"].add(commit.hexsha)
            for path in commit.stats.files:  # type: ignore[reportGeneralTypeIssues]
                if Path(path).suffix not in SUPPORTED_FILE_TYPES:
                    continue
                if path not in self._cache.data["file_data"]:
                    self._cache.data["file_data"][path] = File(
                        path, Path(self._repo.working_dir) / path
                    )
                self._cache.data["file_data"][path].add_commit(commit)

        self._sort_files()
        self._cache.persist()

    def _sort_files(self):
        self._cache.data["sorted_files"] = list(
            sorted(
                self._cache.data["file_data"].keys(),
                key=lambda x: self._cache.data["file_data"][x].get_score(),
                reverse=True,
            )
        )

    def top_files(self):
        return [
            self._cache.data["file_data"][path]
            for path in self._cache.data["sorted_files"]
        ]

    def get_file(self, path: str):
        if path not in self._cache.data["file_data"]:
            raise RuntimeError("File not found or not analyzed yet")
        return self._cache.data["file_data"][path]
