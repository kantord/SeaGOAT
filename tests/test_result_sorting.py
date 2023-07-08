from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager
from codector.engine import Engine
from codector.result import Result
from codector.sources import ripgrep, chroma
from tests.test_file import pytest


@contextmanager
def mock_sources_context(repo, ripgrep_lines, chroma_lines):
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
        mock_ripgrep.return_value = {"fetch": create_mock_fetch(repo, ripgrep_lines)}
        mock_chroma.return_value = {"fetch": create_mock_fetch(repo, chroma_lines)}
        yield


@pytest.fixture(name="create_prepared_codector")
def _create_prepared_codector(repo):
    def _prepared_codector(query, ripgrep_lines, chroma_lines):
        with mock_sources_context(repo, ripgrep_lines, chroma_lines):
            codector = Engine(repo.working_dir)
            codector.query(query)
            codector.fetch_sync()
            return codector

    return _prepared_codector


def test_sort_results_test1(create_prepared_codector):
    ripgrep_lines = {
        "file1.md": [(1, 10.0), (2, 4.0)],
        "file2.md": [(1, 5.0)],
    }
    chroma_lines = {
        "file2.md": [(2, 6.0)],
        "file3.md": [(1, 4.5)],
    }
    my_query = "fake query"

    codector = create_prepared_codector(my_query, ripgrep_lines, chroma_lines)
    results = codector.get_results()

    assert [result.path for result in results] == ["file1.md", "file3.md", "file2.md"]


def test_sort_results_test2(create_prepared_codector):
    ripgrep_lines = {
        "file1.md": [(1, 10.0)],
        "file2.md": [(1, 15.0)],
    }
    chroma_lines = {
        "file3.md": [(1, 5.0)],
    }
    my_query = "fake query"

    codector = create_prepared_codector(my_query, ripgrep_lines, chroma_lines)
    results = codector.get_results()

    assert [result.path for result in results] == ["file3.md", "file1.md", "file2.md"]


def test_missing_file_in_one_source(create_prepared_codector):
    ripgrep_lines = {
        "file1.md": [(1, 10.0)],
        "file2.md": [(1, 5.0)],
    }
    chroma_lines = {
        "file1.md": [(1, 6.0)],
    }
    my_query = "fake query"

    codector = create_prepared_codector(my_query, ripgrep_lines, chroma_lines)
    results = codector.get_results()

    assert [result.path for result in results] == ["file2.md", "file1.md"]


def test_no_lines(create_prepared_codector):
    ripgrep_lines = {}
    chroma_lines = {}
    my_query = "fake query"

    codector = create_prepared_codector(my_query, ripgrep_lines, chroma_lines)
    results = codector.get_results()

    assert results == []
