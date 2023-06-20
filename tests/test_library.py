from codector.library import Codector


def test_returns_file_list_1(repo):
    codector = Codector(repo.working_dir)
    assert set(codector.files()) == {"file1.md", "file2.py", "file3.py", "file4.js"}


def test_returns_file_list_2(repo):
    codector = Codector(repo.working_dir)
    repo.add_file_change_commit(
        file_name="new_file.cpp",
        contents="#include <iostream>",
        author=repo.actors["John Doe"],
        commit_message="Initial commit for C++ file",
    )
    assert set(codector.files()) == {
        "file1.md",
        "file2.py",
        "file3.py",
        "file4.js",
        "new_file.cpp",
    }


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

    assert "file_on_other_branch.cpp" in codector.files()
