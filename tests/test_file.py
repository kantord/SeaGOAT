from pathlib import Path

import pytest

from seagoat.gitfile import GitFile
from seagoat.repository import Repository


@pytest.fixture
def repo_folder(repo):
    with open(Path(repo.working_dir) / "hello.md", "w", encoding="utf-8") as hello_file:
        hello_file.write("Hello world!")
    yield Path(repo.working_dir)


@pytest.mark.parametrize(
    "score, commit_messages",
    [
        pytest.param(
            0.543245,
            [
                "First commit",
                "Second commit",
            ],
            id="lists-all-commit-messages",
        ),
        pytest.param(
            0.234234,
            ["unrelated commit"],
            id="with-a-single-commit",
        ),
    ],
)
def test_file_metadata(repo_folder, snapshot, score, commit_messages):
    my_file = GitFile(
        None,
        "hello.md",
        repo_folder / "hello.md",
        "4eb3bd99c328ed9fdc4eeed781af39f19378fae7",
        score,
        commit_messages,
    )

    assert my_file.get_metadata() == snapshot


def test_ignores_almost_empty_lines_in_chunks(repo):
    repo.add_file_change_commit(
        file_name="example.py",
        contents="""#this is a Python file

# xd

class FooBar:


def __init__(self):
        pass""",
        commit_message=".",
    )

    my_repositoy = Repository(repo.working_dir)
    my_repositoy.analyze_files()
    my_file = my_repositoy.get_file("example.py")

    assert {item.codeline for item in my_file.get_chunks()} == {1, 5, 8, 9}
    line5 = next(item for item in my_file.get_chunks() if item.codeline == 5)
    found_lines = line5.chunk.split("###")[0].splitlines()
    assert found_lines == [
        "#this is a Python file",
        "",
        "# xd",
        "",
        "class FooBar:",
        "",
        "",
        "def __init__(self):",
    ]


def test_file_lines_are_read_once_per_git_object(repo, mocker):
    # Every query builds new GitFile objects for the same files
    repo.add_file_change_commit(
        file_name="cached.py", contents="a = 1\nb = 2\n", commit_message="."
    )
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    read_blob = mocker.spy(repository, "get_blob_data")

    first = repository.get_file("cached.py").lines
    second = repository.get_file("cached.py").lines

    assert first == second == {1: "a = 1", 2: "b = 2"}
    assert read_blob.call_count == 1


def test_a_new_version_of_a_file_has_its_new_lines(repo):
    repo.add_file_change_commit(
        file_name="changed.py", contents="old = 1\n", commit_message="."
    )
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    assert repository.get_file("changed.py").lines == {1: "old = 1"}

    repo.add_file_change_commit(
        file_name="changed.py", contents="new = 2\n", commit_message="."
    )
    repository.analyze_files()

    assert repository.get_file("changed.py").lines == {1: "new = 2"}
