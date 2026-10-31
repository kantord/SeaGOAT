"""Run git for made-up test repositories, isolated from the developer's setup."""

import os
import subprocess
from pathlib import Path

AUTHOR_NAME = "Test Author"
AUTHOR_EMAIL = "test@example.com"


def git_env(**extra: str) -> dict:
    env = os.environ.copy()
    # Ignore the developer's git configuration so no commit signing, hooks or
    # other settings leak into the made-up commits and the repo stays
    # reproducible (same commit IDs no matter who builds it).
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            **extra,
        }
    )
    return env


def commit_env(date: str | None = None) -> dict:
    dates = (
        {} if date is None else {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    )
    return git_env(
        GIT_AUTHOR_NAME=AUTHOR_NAME,
        GIT_AUTHOR_EMAIL=AUTHOR_EMAIL,
        GIT_COMMITTER_NAME=AUTHOR_NAME,
        GIT_COMMITTER_EMAIL=AUTHOR_EMAIL,
        **dates,
    )


def run_git(repo_path: str | Path, *args: str, env: dict | None = None) -> None:
    subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env if env is not None else git_env(),
    )


def make_git_repo(path: Path) -> Path:
    """Create a plain git repository with one commit, creating parents as needed."""
    path.mkdir(parents=True, exist_ok=True)
    run_git(path, "init", "-b", "master")
    (path / "README.md").write_text(f"hello from {path}\n", encoding="utf-8")
    run_git(path, "add", "README.md")
    run_git(path, "commit", "-m", "initial commit", env=commit_env())
    return path
