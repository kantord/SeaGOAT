import os
from pathlib import Path

import pytest

from seagoat.repository import Repository
from seagoat.sources.ripgrep import initialize


@pytest.fixture(name="initialize_empty_source")
def _initialize_empty_source(repo):
    # Remove any pre-populated supported files so the ripgrep cache ends up empty
    for filename in ["file1.md", "file2.py", "file3.py", "file4.js", "file4.md"]:
        p = Path(repo.working_dir) / filename
        if p.exists():
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    # Optionally add an unsupported file to ensure repository contains files but none supported
    unsupported = Path(repo.working_dir) / "rock.mp3"
    unsupported.write_text("12345", encoding="utf-8")

    def _init():
        my_repo = Repository(repo.working_dir)
        my_repo.analyze_files()
        source = initialize(my_repo)
        # This should build an empty cache file and must not raise due to mmap on empty files
        source["cache_repo"]()
        return source["fetch"]

    return _init


def test_mmap_empty_file_issue_945(initialize_empty_source):
    fetch = initialize_empty_source()
    # Should not raise and should return no results for empty input cache
    results = list(fetch("anything", limit=10))
    assert results == []


def test_non_empty_mapping_unchanged(repo):
    contents = """
hello foo bar baz
hello foo bar baz 23
"""
    repo.add_file_change_commit(
        file_name="sample.txt",
        contents=contents,
        author=repo.actors["John Doe"],
        commit_message="Add sample text",
    )

    my_repo = Repository(repo.working_dir)
    my_repo.analyze_files()
    source = initialize(my_repo)
    source["cache_repo"]()
    fetch = source["fetch"]

    fetched_results = list(fetch("baz|23", limit=100))
    # Behavior for non-empty files should remain intact
    assert len(fetched_results) == 1
    file = fetched_results[0]
    assert file.gitfile.path == "sample.txt"
    assert set(file.lines) != set()  # we should have some matching lines

