from seagoat.cache import Cache
from seagoat.engine import RepositoryData
from seagoat.repository import Repository
from seagoat.sources.ripgrep import initialize
from tests.conftest import Path
from tests.test_ripgrep import pytest


@pytest.fixture(name="initialize_source")
def _initialize_source():
    def _initalize(repo):
        path = repo.working_dir
        cache = Cache[RepositoryData](
            "cache",
            Path(path),
            {
                "required_commits": set(),
                "last_analyzed_version_of_branch": {},
                "file_data": {},
                "commits_already_analyzed": set(),
                "chunks_already_analyzed": set(),
                "sorted_files": [],
            },
        )
        source = initialize(Repository(path, cache))

        return source["fetch"]

    return _initalize


def test_fetch_and_initialize(repo, initialize_source):
    contents = """
234
hello foo bar baz
hello foo bar baz 23

234234
345 adaf
2345234523452345235
2345
"""
    repo.add_file_change_commit(
        file_name="file1.txt",
        contents=contents,
        author=repo.actors["John Doe"],
        commit_message="Initial commit for text file",
    )

    fetch = initialize_source(repo)
    fetched_files = fetch("[0-9]{2,10}", limit=400)

    assert len(fetched_files) == 1
    file = next(iter(fetched_files))
    assert file.path == "file1.txt"
    assert set(line for line in file.lines) == {2, 4, 6, 7, 8, 9}


def test_whitespace_is_used_as_or_operator(repo, initialize_source):
    contents = """
234
hello foo bar baz
hello foo bar baz 23

234234
345 adaf
2345234523452345235
2345
baz
bar
b3
"""
    repo.add_file_change_commit(
        file_name="file1.txt",
        contents=contents,
        author=repo.actors["John Doe"],
        commit_message="Initial commit for text file",
    )

    fetch = initialize_source(repo)
    fetched_files = fetch("[0-9]{2,10} baz bar b[0-9]", limit=100)

    assert len(fetched_files) == 1
    file = next(iter(fetched_files))
    assert file.path == "file1.txt"
    assert set(line for line in file.lines) == {2, 3, 4, 6, 7, 8, 9, 10, 11, 12}
