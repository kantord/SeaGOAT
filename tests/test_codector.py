from unittest.mock import patch

from codector.codector import Codector
from codector.file import File


def test_returns_file_list_1(repo):
    codector = Codector(repo.working_dir)
    codector.analyze_files()

    assert set(file.path for file in codector.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
    }
    assert codector.get_file("file1.md").commit_messages == [
        "Update to Markdown file",
        "Initial commit for Markdown file",
    ]


def test_returns_file_list_2(repo):
    codector = Codector(repo.working_dir)
    repo.add_file_change_commit(
        file_name="new_file.cpp",
        contents="#include <iostream>",
        author=repo.actors["John Doe"],
        commit_message="Initial commit for C++ file",
    )
    codector.analyze_files()

    assert set(file.path for file in codector.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "new_file.cpp",
    }
    assert codector.get_file("new_file.cpp").commit_messages == [
        "Initial commit for C++ file"
    ]


def test_gets_files_from_all_branches(repo):
    codector = Codector(repo.working_dir)
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
    codector.analyze_files()

    assert any(file.path == "file_on_other_branch.cpp" for file in codector.top_files())


def test_file_change_many_times_is_first_result(repo):
    codector = Codector(repo.working_dir)
    for i in range(10):
        repo.add_file_change_commit(
            file_name="new_file.txt",
            contents=f"{i}",
            author=repo.actors["John Doe"],
            commit_message="add my file",
        )
    codector.analyze_files()

    assert codector.top_files()[0].path == "new_file.txt"


def test_newer_change_can_beat_frequent_change_in_past(repo):
    codector = Codector(repo.working_dir)
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
    codector.analyze_files()

    assert codector.top_files()[0].path == "new_file.txt"


def test_ignores_certain_branches(repo):
    codector = Codector(repo.working_dir)
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
    codector.analyze_files()

    assert not any(
        file.path == "file_on_other_branch.cpp" for file in codector.top_files()
    )


def test_commits_are_not_analyzed_twice(repo):
    codector = Codector(repo.working_dir)
    repo.add_file_change_commit(
        file_name="file_to_test.cpp",
        contents="",
        author=repo.actors["John Doe"],
        commit_message="add my file",
    )

    with patch.object(File, "add_commit", autospec=True) as mock_add_commit:
        codector.analyze_files()
        first_call_count = mock_add_commit.call_count

        codector.analyze_files()
        second_call_count = mock_add_commit.call_count

    assert first_call_count == second_call_count


def test_analysis_results_are_persisted_between_runs(repo):
    codector1 = Codector(repo.working_dir)
    codector1.analyze_files()
    del codector1
    codector2 = Codector(repo.working_dir)
    with patch.object(File, "add_commit", autospec=True) as mock_add_commit:
        codector2.analyze_files()
        call_count = mock_add_commit.call_count

    assert call_count == 0
    assert set(file.path for file in codector2.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
    }
