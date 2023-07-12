# pylint: disable=protected-access
from unittest.mock import patch

from freezegun import freeze_time

from seagoat.engine import Engine
from seagoat.file import File


def test_returns_file_list_1(repo):
    seagoat = Engine(repo.working_dir)
    seagoat.analyze_codebase()

    assert set(file.path for file in seagoat.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
    }
    assert seagoat.repository.get_file("file1.md").commit_messages == {
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

    assert set(file.path for file in seagoat.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "new_file.cpp",
    }
    assert seagoat.repository.get_file("new_file.cpp").commit_messages == {
        "Initial commit for C++ file"
    }


def test_gets_files_from_all_branches(repo):
    seagoat = Engine(repo.working_dir)
    main = repo.active_branch
    new_branch = repo.create_head("other_branch")
    new_branch.checkout()
    repo.add_file_change_commit(
        file_name="file_on_other_branch.cpp",
        contents="",
        author=repo.actors["John Doe"],
        commit_message="add my file",
    )
    main.checkout()
    seagoat.analyze_codebase()

    assert any(
        file.path == "file_on_other_branch.cpp"
        for file in seagoat.repository.top_files()
    )


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
    seagoat.analyze_codebase()

    assert seagoat.repository.top_files()[0].path == "new_file.txt"


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

    assert seagoat.repository.top_files()[0].path == "new_file.txt"


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
        for file in seagoat.repository.top_files()
    )


def test_commits_are_not_analyzed_twice(repo):
    seagoat = Engine(repo.working_dir)
    repo.add_file_change_commit(
        file_name="file_to_test.cpp",
        contents="",
        author=repo.actors["John Doe"],
        commit_message="add my file",
    )

    with patch.object(File, "add_commit", autospec=True) as mock_add_commit:
        seagoat.analyze_codebase()
        first_call_count = mock_add_commit.call_count

        seagoat.analyze_codebase()
        second_call_count = mock_add_commit.call_count

    assert first_call_count == second_call_count


def test_analysis_results_are_persisted_between_runs(repo):
    seagoat1 = Engine(repo.working_dir)
    seagoat1.analyze_codebase()
    del seagoat1
    seagoat2 = Engine(repo.working_dir)
    with patch.object(File, "add_commit", autospec=True) as mock_add_commit:
        seagoat2.analyze_codebase()
        call_count = mock_add_commit.call_count

    assert call_count == 0
    assert set(file.path for file in seagoat2.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
    }


def test_damaged_cache_doesnt_crash_app_1(repo):
    seagoat1 = Engine(repo.working_dir)
    seagoat1.analyze_codebase()
    cache_folder = seagoat1._cache.get_cache_folder()
    with open(cache_folder / "cache", "rb") as input_file:
        data = input_file.read()
    damaged_data = data[:-1]
    with open(cache_folder / "cache", "wb") as output_file:
        output_file.write(damaged_data)
    del seagoat1
    seagoat2 = Engine(repo.working_dir)
    with patch.object(File, "add_commit", autospec=True) as mock_add_commit:
        seagoat2.analyze_codebase()
        call_count = mock_add_commit.call_count

    assert call_count != 0
    assert set(file.path for file in seagoat2.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
    }


def test_damaged_cache_doesnt_crash_app_2(repo):
    seagoat1 = Engine(repo.working_dir)
    seagoat1.analyze_codebase()
    cache_folder = seagoat1._cache.get_cache_folder()
    with open(cache_folder / "cache", "wb"):
        pass
    del seagoat1
    seagoat2 = Engine(repo.working_dir)
    with patch.object(File, "add_commit", autospec=True) as mock_add_commit:
        seagoat2.analyze_codebase()
        call_count = mock_add_commit.call_count

    assert call_count != 0
    assert set(file.path for file in seagoat2.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
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

    assert set(file.path for file in seagoat.repository.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
    }
    assert seagoat.repository.get_file("file1.md").commit_messages == {
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
        seagoat1.repository.get_file("file1.md").get_score()
        == seagoat2.repository.get_file("file1.md").get_score()
    )
