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
