import subprocess
from pathlib import Path

import run


def test_risky_paths_are_split_by_when_they_run():
    refused, read_first = run.risky(
        [
            ".claude/settings.json",
            ".envrc",
            "tests/conftest.py",
            "pyproject.toml",
            "tools/worker/verify.sh",
            "seagoat/server.py",
            "docs/claude/notes.md",
            "tests/test_pyproject.toml.py",
        ]
    )
    assert refused == [".claude/settings.json", ".envrc"]
    assert read_first == [
        "tests/conftest.py",
        "pyproject.toml",
        "tools/worker/verify.sh",
    ]


def test_risky_paths_catch_hidden_config_anywhere():
    refused, read_first = run.risky(
        [
            "CLAUDE.md",
            "docs/AGENTS.md",
            "sub/.cargo/config.toml",
            "pytest.ini",
            "src/lib.rs",
        ]
    )
    assert refused == ["CLAUDE.md", "docs/AGENTS.md"]
    assert read_first == ["sub/.cargo/config.toml", "pytest.ini"]


def test_risky_paths_catch_a_directory_replaced_by_a_file_or_symlink():
    refused, read_first = run.risky(
        [".claude", "sub/.vscode", "tools/worker", "evil/x"]
    )
    assert refused == [".claude", "sub/.vscode"]
    assert read_first == ["tools/worker"]


def test_patch_symlinks_finds_new_and_changed_symlinks(tmp_path: Path):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    git("init", "-q")
    (tmp_path / "plain").write_text("x")
    (tmp_path / "was_file").write_text("x")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    (tmp_path / "was_file").unlink()
    (tmp_path / "was_file").symlink_to("evil")
    (tmp_path / ".claude").symlink_to("evil")
    (tmp_path / "plain").write_text("y")
    git("add", "-A")
    patch = tmp_path / "p.patch"
    patch.write_text(git("diff", "--cached", "--binary", "--no-renames"))
    assert sorted(run.patch_symlinks(patch)) == [".claude", "was_file"]
