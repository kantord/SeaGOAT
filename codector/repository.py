from typing import Dict, List, Set
from pathlib import Path
import pickle

from git.repo import Repo
from tqdm import tqdm

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


class Repository:
    def __init__(self, path: str, cache_path: Path) -> None:
        self._repo = Repo(path)
        self._cache_file = cache_path / "cache"
        self._sorted_files: List[str] = []
        self.file_data: Dict[str, File] = {}
        self._commits_already_analyzed: Set[str] = set()
        self._required_commits: Set[str] = set()
        self._last_analyzed_version_of_branch: Dict[str, str] = {}
        self._load_cache()

    def _load_cache(self):
        try:
            with open(self._cache_file, "rb") as cache_file:
                cache_tuple = pickle.load(cache_file)
                (
                    self._commits_already_analyzed,
                    self.file_data,
                    self._sorted_files,
                    self._required_commits,
                    self._last_analyzed_version_of_branch,
                ) = cache_tuple
        except (FileNotFoundError, pickle.UnpicklingError, EOFError):
            print("Cache not found, need to analyze files")

    def _write_cache(self):
        with open(self._cache_file, "wb") as cache_file:
            cache_tuple = (
                self._commits_already_analyzed,
                self.file_data,
                self._sorted_files,
                self._required_commits,
                self._last_analyzed_version_of_branch,
            )
            pickle.dump(cache_tuple, cache_file)

    def _get_all_commits(self):
        for branch in tqdm(self._repo.branches, desc="Analyzing branches"):
            if branch.name in IGNORED_BRANCHES:
                continue
            if (
                self._last_analyzed_version_of_branch.get(branch.name)
                == branch.commit.hexsha
            ):
                continue
            for commit in self._repo.iter_commits(branch):
                self._required_commits.add(commit.hexsha)
            self._last_analyzed_version_of_branch[branch.name] = branch.commit.hexsha

        return (self._repo.commit(commit) for commit in self._required_commits)

    def analyze_files(self):
        for commit in tqdm(
            self._get_all_commits(),
            desc="Analyzing commits",
            total=len(self._required_commits),
        ):
            if commit.hexsha in self._commits_already_analyzed:
                continue
            self._commits_already_analyzed.add(commit.hexsha)
            for path in commit.stats.files:  # type: ignore[reportGeneralTypeIssues]
                if Path(path).suffix not in SUPPORTED_FILE_TYPES:
                    continue
                if path not in self.file_data:
                    self.file_data[path] = File(
                        path, Path(self._repo.working_dir) / path
                    )
                self.file_data[path].add_commit(commit)

        self._sort_files()
        self._write_cache()

    def _sort_files(self):
        self._sorted_files = list(
            sorted(
                self.file_data.keys(),
                key=lambda x: self.file_data[x].get_score(),
                reverse=True,
            )
        )

    def top_files(self):
        return [self.file_data[path] for path in self._sorted_files]

    def get_file(self, path: str):
        if path not in self.file_data:
            raise RuntimeError("File not found or not analyzed yet")
        return self.file_data[path]
