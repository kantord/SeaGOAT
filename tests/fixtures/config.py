"""Write repository config files that SeaGOAT refuses to load."""

from pathlib import Path

NOT_A_LIST = "server:\n  repositories: this-is-not-a-list\n"
NOT_A_NUMBER = "server:\n  readMaxCommits: not-a-number\n"


def write_invalid_config(repo_path: str | Path, content: str = NOT_A_LIST) -> None:
    (Path(repo_path) / ".seagoat.yml").write_text(content, encoding="utf-8")
