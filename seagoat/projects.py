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
