from codector.library import Codector


def test_returns_file_list_1(repo):
    codector = Codector(repo.working_dir)
    assert set(codector.files()) == {"file1.md", "file2.py", "file3.py", "file4.js"}
