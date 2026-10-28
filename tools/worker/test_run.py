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
