import os
import subprocess
import threading
from pathlib import Path
from typing import Any, NamedTuple

from seagoat.utils.config import get_config_values
from seagoat.utils.server import normalize_repo_path


class NotAGitRepo(Exception):
    pass


class UnknownProject(Exception):
    pass


class Project(NamedTuple):
    repo_path: str  # normalized repository root
    config: dict  # read once, when the project is created
    queue: Any  # whatever queue_factory returned


def find_repositories_in_directory(path: str) -> list[str]:
    """Return the git repository roots among the direct subdirectories of path.

    Only direct children are considered (no deeper search): a subdirectory is
    included exactly when it is itself a repository root.
    """
    try:
        children = [
            entry.path
            for entry in os.scandir(path)
            if entry.is_dir(follow_symlinks=False)
        ]
    except OSError:
        return []
    repositories = []
    for child in children:
        try:
            root = git_root(child)
        except NotAGitRepo:
            continue
        if normalize_repo_path(root) == normalize_repo_path(child):
            repositories.append(root)
    return sorted(repositories, key=normalize_repo_path)


def git_root(path: str) -> str:
    try:
        output = subprocess.check_output(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise NotAGitRepo(path) from error
    return output.strip()


def resolve_repo_path(path: str) -> str:
    """Return the repository root containing path, or path itself when path
    is not inside a git repository."""
    try:
        return git_root(path)
    except NotAGitRepo:
        return path


class Projects:
    def __init__(self, queue_factory, resolve=git_root):
        self._queue_factory = queue_factory
        self._resolve = resolve
        self._projects: dict[str, Project] = {}
        self._lock = threading.Lock()

    def get(self, repo_path) -> Project:
        root = self._resolve(repo_path)
        key = normalize_repo_path(root)
        with self._lock:
            project = self._projects.get(key)
            if project is None:
                config = get_config_values(Path(key))
                queue = self._queue_factory(key, config)
                project = Project(repo_path=key, config=config, queue=queue)
                self._projects[key] = project
            return project

    def find(self, repo_path) -> Project:
        # For callers that may not create projects: creating one runs git in the
        # named directory, whose .git/config can run commands.
        key = normalize_repo_path(repo_path)
        try:
            return self._projects[key]
        except KeyError:
            raise UnknownProject(repo_path) from None

    def repo_paths(self) -> list[str]:
        with self._lock:
            return list(self._projects.keys())
