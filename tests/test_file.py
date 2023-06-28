# pylint: disable=redefined-outer-name

from pathlib import Path
import time
from codector.file import File
from tests.conftest import pytest


@pytest.fixture
def repo_folder(repo):
    with open(Path(repo.working_dir) / "hello.md", "w", encoding="utf-8") as hello_file:
        hello_file.write("Hello world!")
    yield Path(repo.working_dir)


# pylint: disable-next=too-few-public-methods
class Commit:
    def __init__(self, message, committed_date=0):
        self.message = message
        self.committed_date = committed_date


def test_file_returns_global_metadata_1(repo_folder, snapshot):
    my_file = File("hello.md", repo_folder / "hello.md")
    my_file.add_commit(Commit("First commit for this"))
    my_file.add_commit(Commit("Another commit for this"))

    assert my_file.get_metadata() == snapshot


def test_file_returns_global_metadata_2(repo_folder, snapshot):
    my_file = File("hello.md", repo_folder / "hello.md")
    my_file.add_commit(Commit("Unrelated commit"))

    assert my_file.get_metadata() == snapshot


def test_handles_files_that_were_edited_today(repo_folder, snapshot):
    my_file = File("hello.md", repo_folder / "hello.md")
    my_file.add_commit(Commit("Unrelated commit", int(time.time())))

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

    my_file = File("example.py", str(Path(repo.working_dir) / "example.py"))
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
