from codector.library import Codector


def test_returns_file_list_1(repo):
    codector = Codector(repo.working_dir)
    codector.analyze_files()

    assert set(file.path for file in codector.top_files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
    }
    file1 = [file for file in codector.top_files() if file.path == "file1.md"][0]
    assert file1.commit_messages == {
        "Initial commit for Markdown file",
        "Update to Markdown file",
    }


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
    new_file = [file for file in codector.top_files() if file.path == "new_file.cpp"][0]
    assert new_file.commit_messages == {"Initial commit for C++ file"}


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
