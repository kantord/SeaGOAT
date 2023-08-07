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
                "last_analyzed_version_of_branch": {},
                "required_commits": set(),
                "commits_already_analyzed": set(),
                "file_data": {},
                "sorted_files": [],
                "chunks_already_analyzed": set(),
            },
        )
        source = initialize(Repository(path, cache))

        return source["fetch"]

    return _initalize


def test__fetch_and_initialize(repo, initialize_source):
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
    fetched_files = fetch("[0-9]{2,10}")

    assert len(fetched_files) == 1
    file = next(iter(fetched_files))
    assert file.path == "file1.txt"
    assert set(line.line for line in file.lines) == {2, 4, 6, 7, 8, 9}
