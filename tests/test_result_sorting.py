from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from seagoat.engine import Engine
from seagoat.result import Result
from seagoat.sources import chroma
from seagoat.sources import ripgrep
from tests.test_file import pytest


@contextmanager
def mock_sources_context(repo, ripgrep_lines, chroma_lines):
    # pylint: disable-next=unused-argument
    def noop(*args, **kwargs):
        pass

    def create_mock_fetch(repo, file_lines):
        def mock_fetch(_):
            results = []
            for file_path, lines in file_lines.items():
                full_path = Path(repo.working_dir) / file_path
                result = Result(path=file_path, full_path=full_path)
                for line, vector_distance in lines:
                    result.add_line(line=line, vector_distance=vector_distance)
                results.append(result)
            return results

        return mock_fetch

    for file_path in set(list(ripgrep_lines.keys()) + list(chroma_lines.keys())):
        repo.add_file_change_commit(
            file_name=file_path,
            contents="\n" * 50,
            author=repo.actors["John Doe"],
            commit_message=f"Add {file_path}",
        )

    with patch.object(ripgrep, "initialize") as mock_ripgrep, patch.object(
        chroma, "initialize"
    ) as mock_chroma:
        mock_ripgrep.return_value = {
            "fetch": create_mock_fetch(repo, ripgrep_lines),
            "cache_chunk": noop,
        }
        mock_chroma.return_value = {
            "fetch": create_mock_fetch(repo, chroma_lines),
            "cache_chunk": noop,
        }
        yield


@pytest.fixture(name="create_prepared_seagoat")
def _create_prepared_seagoat(repo):
    def _prepared_seagoat(query, ripgrep_lines, chroma_lines):
        with mock_sources_context(repo, ripgrep_lines, chroma_lines):
            seagoat = Engine(repo.working_dir)
            seagoat.analyze_codebase()
            seagoat.query(query)
            seagoat.fetch_sync()
            return seagoat

    return _prepared_seagoat


def test_sort_results_test1(create_prepared_seagoat):
    ripgrep_lines = {
        "file1.md": [(1, 10.0), (2, 4.0)],
        "file2.md": [(1, 5.0)],
    }
    chroma_lines = {
        "file2.md": [(2, 6.0)],
        "file3.md": [(1, 4.5)],
    }
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.get_results()

    assert [result.path for result in results] == ["file1.md", "file3.md", "file2.md"]


def test_sort_results_test2(create_prepared_seagoat):
    ripgrep_lines = {
        "file1.md": [(1, 10.0)],
        "file2.md": [(1, 15.0)],
    }
    chroma_lines = {
        "file3.md": [(1, 5.0)],
    }
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.get_results()

    assert [result.path for result in results] == ["file3.md", "file1.md", "file2.md"]


def test_missing_file_in_one_source(create_prepared_seagoat):
    ripgrep_lines = {
        "file1.md": [(1, 10.0)],
        "file2.md": [(1, 5.0)],
    }
    chroma_lines = {
        "file1.md": [(1, 6.0)],
    }
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.get_results()

    assert [result.path for result in results] == ["file2.md", "file1.md"]


def test_no_lines(create_prepared_seagoat):
    ripgrep_lines = {}
    chroma_lines = {}
    my_query = "fake query"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    results = seagoat.get_results()

    assert results == []


def test_file_edits_influence_order(create_prepared_seagoat, repo):
    repo.add_file_change_commit(
        file_name="file_few_edits.md",
        contents="Some content",
        author=repo.actors["John Doe"],
        commit_message="Edit file_few_edits.md",
    )

    for i in range(10):
        for j in range(3):
            repo.add_file_change_commit(
                file_name=f"file_with_some_edits_{i}.md",
                contents=f"Some content {i} {j}",
                author=repo.actors["John Doe"],
                commit_message="Edit file_many_edits.md",
            )
            repo.tick_fake_date(days=1)

    for i in range(20):
        repo.add_file_change_commit(
            file_name="file_many_edits.md",
            contents=f"Some content {i}",
            author=repo.actors["John Doe"],
            commit_message="Edit file_many_edits.md",
        )
        repo.tick_fake_date(days=1)

    ripgrep_lines = {
        "file_few_edits.md": [(1, 5.0)],
        "file_many_edits.md": [(1, 6.0)],
    }
    chroma_lines = {
        "file_few_edits.md": [(2, 5.0)],
        "file_many_edits.md": [(1, 6.0)],
    }
    my_query = "asdfadsfdfdffdafafdsfadsf"

    seagoat = create_prepared_seagoat(my_query, ripgrep_lines, chroma_lines)
    seagoat.analyze_codebase()
    results = seagoat.get_results()

    assert [result.path for result in results] == [
        "file_many_edits.md",
        "file_few_edits.md",
    ]
