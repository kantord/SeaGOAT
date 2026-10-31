"""Replace the ripgrep and chroma sources with fixed results for a test repo."""

from contextlib import contextmanager
from unittest.mock import patch

from seagoat.repository import Repository
from seagoat.result import Result
from seagoat.sources import chroma, ripgrep


@contextmanager
def mock_sources_context(repo, ripgrep_lines, chroma_lines):
    def noop(*args, **kwargs):
        pass

    def create_mock_query(repo, file_lines):
        def mock_query(_, __):
            results = []
            repository = Repository(repo.working_dir)
            repository.analyze_files()
            for file_path, lines in file_lines.items():
                gitfile = repository.get_file(file_path)
                result = Result("", gitfile)
                for line, vector_distance in lines:
                    result.add_line(line=line, vector_distance=vector_distance)
                results.append(result)

            del repository
            return results

        return mock_query

    for file_path in set(list(ripgrep_lines.keys()) + list(chroma_lines.keys())):
        repo.add_file_change_commit(
            file_name=file_path,
            contents="\n" * 50,
            commit_message=f"Add {file_path}",
        )

    with (
        patch.object(ripgrep, "initialize") as mock_ripgrep,
        patch.object(chroma, "initialize") as mock_chroma,
    ):
        mock_ripgrep.return_value = {
            "fetch": create_mock_query(repo, ripgrep_lines),
            "cache_chunk": noop,
            "cache_repo": noop,
        }
        mock_chroma.return_value = {
            "fetch": create_mock_query(repo, chroma_lines),
            "cache_chunk": noop,
            "cache_repo": noop,
        }
        yield
