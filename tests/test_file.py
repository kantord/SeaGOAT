# pylint: disable=redefined-outer-name
from pathlib import Path

import pytest

from seagoat.file import File


@pytest.fixture
def repo_folder(repo):
    with open(Path(repo.working_dir) / "hello.md", "w", encoding="utf-8") as hello_file:
        hello_file.write("Hello world!")
    yield Path(repo.working_dir)


def test_file_returns_global_metadata_1(repo_folder, snapshot):
    my_file = File(
        "hello.md",
        repo_folder / "hello.md",
        0.543245,
        [
            "First commit",
            "Second commit",
        ],
    )

    assert my_file.get_metadata() == snapshot


def test_file_returns_global_metadata_2(repo_folder, snapshot):
    my_file = File("hello.md", repo_folder / "hello.md", 0.234234, ["unrelated commit"])

    assert my_file.get_metadata() == snapshot


def test_ignores_almost_empyt_lines_in_chunks(repo):
    repo.add_file_change_commit(
        file_name="example.py",
        contents="""#this is a Python file

# xd

class FooBar:


def __init__(self):
        pass""",
        author=repo.actors["John Doe"],
        commit_message=".",
    )

    my_file = File(
        "example.py", str(Path(repo.working_dir) / "example.py"), 0.234234, []
    )
    assert {item.codeline for item in my_file.get_chunks()} == {1, 5, 8, 9}
    line5 = [item for item in my_file.get_chunks() if item.codeline == 5][0]
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
