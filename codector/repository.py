from pathlib import Path
from typing import Dict, List, Set
from typing_extensions import TypedDict

from git.repo import Repo
from tqdm import tqdm
from codector.cache import Cache

from codector.file import File


IGNORED_BRANCHES = {"gh-pages"}
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


RepositoryData = TypedDict(
    "RepositoryData",
    {
        "last_analyzed_version_of_branch": Dict[str, str],
        "required_commits": Set[str],
        "commits_already_analyzed": Set[str],
        "file_data": Dict[str, File],
        "sorted_files": List[str],
    },
)


class Repository:
    def __init__(self, path: str, cache_path: Path) -> None:
        self._repo = Repo(path)
        self._cache_file = cache_path / "cache"
        self._cache = Cache[RepositoryData](
            self._cache_file,
            {
                "last_analyzed_version_of_branch": {},
                "required_commits": set(),
                "commits_already_analyzed": set(),
                "file_data": {},
                "sorted_files": [],
            },
        )
        self._cache.load()

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
