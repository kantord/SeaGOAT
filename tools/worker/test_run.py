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
