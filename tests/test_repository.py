from pathlib import Path
from typing import Any

from freezegun import freeze_time
from pytest_mock import MockerFixture
from seagoat.engine import Engine
from tests.conftest import MockRepo
from tests.test_server import pytest


def test_returns_file_list_1(repo):
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    assert set(file.path for file, _ in seagoat.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }
    assert set(seagoat.repository.get_file("file1.md").commit_messages) == {
        "Initial commit for Markdown file",
        "Update to Markdown file",
    }


def test_returns_file_list_2(repo):
    seagoat = Engine(repo.working_dir)
    repo.add_file_change_commit(
        file_name="new_file.cpp",
        contents="#include <iostream>",
        author=repo.actors["John Doe"],
        commit_message="Initial commit for C++ file",
    )
    seagoat.analyze_codebase()

    assert set(file.path for file, _ in seagoat.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
        "new_file.cpp",
    }
    assert set(seagoat.repository.get_file("new_file.cpp").commit_messages) == {
        "Initial commit for C++ file"
    }


def test_file_change_many_times_is_first_result(repo):
    seagoat = Engine(repo.working_dir)
    for i in range(10):
        repo.add_file_change_commit(
            file_name="new_file.txt",
            contents=f"{i}",
            author=repo.actors["John Doe"],
            commit_message="add my file",
        )
        repo.tick_fake_date(minutes=1)
    seagoat.analyze_codebase(minimum_chunks_to_analyze=2)

    assert seagoat.repository.top_files()[0][0].path == "new_file.txt"


def test_newer_change_can_beat_frequent_change_in_past(repo):
    seagoat = Engine(repo.working_dir)
    for i in range(10):
        repo.add_file_change_commit(
            file_name="old_file.txt",
            contents=f"{i}",
            author=repo.actors["John Doe"],
            commit_message="add my file",
        )
    repo.tick_fake_date(days=300)
    repo.add_file_change_commit(
        file_name="new_file.txt",
        contents="hello",
        author=repo.actors["John Doe"],
        commit_message="add another file",
    )
    seagoat.analyze_codebase()

    assert seagoat.repository.top_files()[0][0].path == "new_file.txt"


def test_commit_messages_with_three_or_more_colons(repo):
    seagoat = Engine(repo.working_dir)
    commit_messages = set()
    for i in range(5):
        message = "add my file" + ":" * i + "!"
        commit_messages.add(message)
        repo.add_file_change_commit(
            file_name="file.txt",
            contents=f"{i}",
            author=repo.actors["John Doe"],
            commit_message=message,
        )
    seagoat.analyze_codebase()

    assert (
        set(seagoat.repository.get_file("file.txt").commit_messages) == commit_messages
    )


def test_ignores_certain_branches(repo):
    seagoat = Engine(repo.working_dir)
    main = repo.active_branch
    new_branch = repo.create_head("gh-pages")
    new_branch.checkout()
    repo.add_file_change_commit(
        file_name="file_on_other_branch.cpp",
        contents="",
        author=repo.actors["John Doe"],
        commit_message="add my file",
    )
    main.checkout()
    seagoat.analyze_codebase()

    assert not any(
        file.path == "file_on_other_branch.cpp"
        for file, _ in seagoat.repository.top_files()
    )


def test_analysis_results_are_persisted_between_runs(repo):
    seagoat1 = Engine(repo.working_dir)
    seagoat1.analyze_codebase()
    del seagoat1
    seagoat2 = Engine(repo.working_dir)
    seagoat2.analyze_codebase()

    assert set(file.path for file, _ in seagoat2.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }


def test_damaged_cache_doesnt_crash_app_1(repo):
    seagoat1 = Engine(repo.working_dir)
    seagoat1.analyze_codebase()
    cache_folder = seagoat1.cache.get_cache_folder()
    with open(cache_folder / "cache", "rb") as input_file:
        data = input_file.read()
    damaged_data = data[:-1]
    with open(cache_folder / "cache", "wb") as output_file:
        output_file.write(damaged_data)
    del seagoat1
    seagoat2 = Engine(repo.working_dir)
    seagoat2.analyze_codebase()

    assert set(file.path for file, _ in seagoat2.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }


def test_damaged_cache_doesnt_crash_app_2(repo):
    seagoat1 = Engine(repo.working_dir)
    seagoat1.analyze_codebase()
    cache_folder = seagoat1.cache.get_cache_folder()
    with open(cache_folder / "cache", "wb"):
        pass
    del seagoat1
    seagoat2 = Engine(repo.working_dir)
    seagoat2.analyze_codebase()

    assert set(file.path for file, _ in seagoat2.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }


def test_only_returns_supported_file_types(repo):
    seagoat = Engine(repo.working_dir)
    for i in range(10):
        repo.add_file_change_commit(
            file_name=f"new_file.txt.extension{i}",
            contents=f"{i}",
            author=repo.actors["John Doe"],
            commit_message="add my file",
        )
    seagoat.analyze_codebase()

    assert set(file.path for file, _ in seagoat.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }
    assert set(seagoat.repository.get_file("file1.md").commit_messages) == {
        "Initial commit for Markdown file",
        "Update to Markdown file",
    }


def test_file_score_is_recalculated_when_needed(generate_repo):
    with freeze_time("2012-01-14"):
        repo1 = generate_repo()
        seagoat1 = Engine(repo1.working_dir)
        repo1.add_file_change_commit(
            file_name="old_file.txt",
            contents="",
            author=repo1.actors["John Doe"],
            commit_message="add my file",
        )
        repo1.tick_fake_date(days=300)
        repo1.add_file_change_commit(
            file_name="new_file.txt",
            contents="hello",
            author=repo1.actors["John Doe"],
            commit_message="add another file",
        )
        seagoat1.analyze_codebase()

        repo2 = generate_repo()
        seagoat2 = Engine(repo1.working_dir)
        repo2.add_file_change_commit(
            file_name="old_file.txt",
            contents="",
            author=repo2.actors["John Doe"],
            commit_message="add my file",
        )
        seagoat2.analyze_codebase()

    assert (
        seagoat1.repository.get_file("file1.md").score
        == seagoat2.repository.get_file("file1.md").score
    )

    with freeze_time("2018-01-15"):
        repo2.tick_fake_date(days=300)
        repo2.add_file_change_commit(
            file_name="new_file.txt",
            contents="hello",
            author=repo2.actors["John Doe"],
            commit_message="add another file",
        )
        seagoat2.analyze_codebase()

    assert (
        seagoat1.repository.get_file("file1.md").score
        != seagoat2.repository.get_file("file1.md").score
    )


def test_does_not_crash_because_of_non_existent_files(repo):
    seagoat = Engine(repo.working_dir)
    (Path(repo.working_dir) / "file1.md").unlink()
    seagoat.analyze_codebase()

    assert set(file.path for file, _ in seagoat.repository.top_files()) == {
        "file2.py",
        "file3.py",
        "file4.js",
        "file4.md",
    }


def test_ignored_files_is_really_ignored(repo: MockRepo):
    file_name = "node_modules/acorn/README.md"
    repo.add_file_change_commit(
        file_name=file_name,
        contents="Hello",
        author=repo.actors["John Doe"],
        commit_message="Incidentally commited node_modules.",
    )
    repo.add_file_change_commit(
        file_name=".gitignore",
        contents="node_modules",
        author=repo.actors["John Doe"],
        commit_message="Added node_modules to gitignore.",
    )
    repo.add_file_delete_commit(
        file_name=file_name,
        author=repo.actors["John Doe"],
        commit_message="Removed node_modules.",
    )
    # File is added in the filesystem, but should be ignored by git.
    file_path = Path(repo.working_dir) / file_name
    file_path.write_text("Hello.")

    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    top_files = set(file.path for file, _ in seagoat.repository.top_files())

    assert file_name not in top_files


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks_to_analyze", [1, 2, 4])
async def test_allows_limiting_how_many_files_are_automatically_analized(
    repo, chunks_to_analyze
):
    seagoat = Engine(repo.working_dir)
    repo.add_file_change_commit(
        file_name="new_file.cpp",
        contents="#include <iostream>",
        author=repo.actors["John Doe"],
        commit_message="Initial commit for C++ file",
    )
    seagoat.analyze_codebase(minimum_chunks_to_analyze=chunks_to_analyze)

    assert len(seagoat.cache.data["chunks_already_analyzed"]) == chunks_to_analyze


@pytest.mark.parametrize(
    "config,expected_extra_args",
    [
        pytest.param({}, ["--max-count=5000"], id="default"),
        pytest.param(
            {"readMaxCommits": 100}, ["--max-count=100"], id="specific-number"
        ),
        pytest.param({"readMaxCommits": None}, [], id="unlimited"),
    ],
)
def test_max_count_is_added_for_read_max_commits_setting(
    repo: MockRepo,
    mocker: MockerFixture,
    config: dict[str, Any],
    expected_extra_args: list[str],
):
    repository = Engine(repo.working_dir).repository
    repository.config["server"].update(config)
    mock = mocker.spy(repository, "_git_log_extra_options")

    repository.analyze_files()

    assert mock.spy_return == expected_extra_args
