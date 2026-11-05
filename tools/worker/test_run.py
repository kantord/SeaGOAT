import subprocess
from pathlib import Path

import pytest
import run


def test_outcome_keeps_a_red_patch_apart_and_leaves_the_rest_as_it_was():
    assert run.outcome("GREEN", 120) == "apply"
    assert run.outcome("GREEN", 0) == "nothing"
    assert run.outcome("RED", 120) == "apply_red"
    # a RED run with nothing to keep, or no patch file, keeps nothing
    assert run.outcome("RED", 0) == "none"
    assert run.outcome("RED", None) == "none"
    assert run.outcome("GREEN", None) == "none"
    # BLOCKED never applies, even with a patch; other failures keep nothing
    assert run.outcome("BLOCKED", 120) == "blocked"
    assert run.outcome("FATAL", 120) == "none"
    assert run.outcome(None, None) == "none"


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


def test_patch_paths_reads_text_and_binary_paths(tmp_path: Path):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    git("init", "-q")
    (tmp_path / "a.txt").write_text("one\n")
    # NUL bytes in the first 8000 make git treat it as binary (numstat "-	-	path").
    (tmp_path / "new.bin").write_bytes(bytes(range(256)) * 40)
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    (tmp_path / "new.bin").write_bytes(bytes(range(256)) * 40 + b"\xff")
    git("add", "-A")
    patch = tmp_path / "p.patch"
    patch.write_text(git("diff", "--cached", "--binary", "--no-renames"))
    # git reports the binary file as "-	-	path" instead of added/deleted counts...
    numstat = git("apply", "--numstat", "-z", str(patch))
    assert "-\t-\tnew.bin" in numstat
    # ...and patch_paths still turns both lines into clean paths.
    assert run.patch_paths(patch) == ["a.txt", "new.bin"]


def test_git_error_reports_command_and_stderr():
    with pytest.raises(SystemExit) as exc:
        run.git("status", "--this-flag-does-not-exist")
    message = str(exc.value)
    assert "git status --this-flag-does-not-exist failed" in message
    assert "unknown option `this-flag-does-not-exist'" in message


def test_unique_dir_suffixes_same_second_collisions(tmp_path: Path):
    stem = "slug-20260101-000000"
    first = run.unique_dir(tmp_path, stem)
    second = run.unique_dir(tmp_path, stem)
    third = run.unique_dir(tmp_path, stem)
    assert first == tmp_path / stem
    assert second == tmp_path / f"{stem}-2"
    assert third == tmp_path / f"{stem}-3"
    assert first.is_dir() and second.is_dir() and third.is_dir()


MSB_SH = Path(__file__).resolve().parent / "msb.sh"


def _fake_msb(directory: Path, version: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    fake = directory / "msb"
    fake.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = --version ]; then echo "msb {version}"; '
        f'else echo "{directory.name} ran: $*"; fi\n'
    )
    fake.chmod(0o755)
    return fake


def _run_msb_sh(tmp_path, path_msb_version):
    home = tmp_path / "home"
    path_dir = tmp_path / "path"
    _fake_msb(path_dir, path_msb_version)
    env = {"MSB_HOME": str(home), "PATH": f"{path_dir}:/usr/bin:/bin"}
    return home, env


def _pinned_version():
    cargo = (Path(__file__).resolve().parent / "Cargo.toml").read_text()
    return cargo.split('microsandbox = { version = "=')[1].split('"')[0]


def test_msb_wrapper_prefers_the_sdk_installed_copy(tmp_path):
    home, env = _run_msb_sh(tmp_path, "99.0.0")
    _fake_msb(home / "bin", _pinned_version())
    done = subprocess.run(
        [MSB_SH, "image", "ls"], env=env, capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "bin ran: image ls"


def test_msb_wrapper_refuses_a_path_msb_of_another_version(tmp_path):
    _, env = _run_msb_sh(tmp_path, "99.0.0")
    done = subprocess.run(
        [MSB_SH, "image", "ls"], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 1
    assert "path ran" not in done.stdout
    assert f"Install msb {_pinned_version()}" in done.stderr


def test_msb_wrapper_uses_a_path_msb_of_the_pinned_version(tmp_path):
    _, env = _run_msb_sh(tmp_path, _pinned_version())
    done = subprocess.run(
        [MSB_SH, "image", "ls"], env=env, capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "path ran: image ls"


def test_worker_scripts_never_call_a_bare_msb():
    worker = Path(__file__).resolve().parent
    for script in (worker / "run.py", worker / "image/build.sh"):
        for line in script.read_text().splitlines():
            code = line.split("#", 1)[0]
            assert '"msb"' not in code and not code.lstrip().startswith("msb "), (
                f"{script.name} calls msb directly: {line.strip()}"
            )
