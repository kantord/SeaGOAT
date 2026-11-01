"""Replace the ripgrep and chroma sources with fixed results for a test repo."""

from contextlib import contextmanager
from unittest.mock import patch

from seagoat.repository import Repository
from seagoat.result import Result
from seagoat.sources import chroma, ripgrep


@contextmanager
def mock_sources_context(
    repo, ripgrep_lines, chroma_lines, embedding=None, storage=None
):
    """Deterministic in-memory stand-in for the real sources.

    ``embedding`` is a callable simulating the embedding step: raising
    seagoat.sources.chroma.EmbeddingError simulates an embedding outage.
    ``storage`` is a callable simulating Chroma storage: any exception raised
    there propagates unchanged, just like a real upsert failure.
    """

    def reset_store(*args, **kwargs):
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

    # In-memory "Chroma" collection: the only place chunks are ever stored.
    store = {}
    batch_calls = []

    def cache_batch(chunks):
        chunks = list(chunks)
        if not chunks:
            return
        if embedding is not None:
            embedding()
        batch_calls.append(list(chunks))
        for chunk in chunks:
            if storage is not None:
                storage()
            store[chunk.chunk_id] = chunk

    def probe_embedding():
        if embedding is not None:
            embedding()

    def indexed_ids(ids):
        return {chunk_id for chunk_id in ids if chunk_id in store}

    def cache_chunk(chunk):
        cache_batch([chunk])

    with (
        patch.object(ripgrep, "initialize") as mock_ripgrep,
        patch.object(chroma, "initialize") as mock_chroma,
    ):
        mock_ripgrep.return_value = {
            "fetch": create_mock_query(repo, ripgrep_lines),
            "cache_batch": reset_store,
            "cache_chunk": reset_store,
            "cache_repo": reset_store,
        }
        chroma_source = {
            "fetch": create_mock_query(repo, chroma_lines),
            "cache_batch": cache_batch,
            "cache_chunk": cache_chunk,
            "cache_repo": reset_store,
            "probe_embedding": probe_embedding,
            "indexed_ids": indexed_ids,
        }
        mock_chroma.return_value = chroma_source
        yield chroma_source, batch_calls
