from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import chromadb
import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.config import Settings

from seagoat.cache import Cache
from seagoat.repository import Repository
from seagoat.sources import chroma

# Focused tests for the atomic Chroma batch contract that the future
# indexing worker relies on: cache_batch, probe_embedding, indexed_ids and
# the EmbeddingError type. Uses real ChromaDB with deterministic fake
# embeddings where practical; no models are downloaded.


def _chunk(chunk_id, text, codeline=3, path="recipes.txt", object_id="deadbeef"):
    return SimpleNamespace(
        chunk_id=chunk_id,
        chunk=text,
        codeline=codeline,
        path=path,
        object_id=object_id,
    )


def _repository(tmp_path):
    return Repository(str(tmp_path))


class _DeterministicEmbeddingFunction(EmbeddingFunction[Documents]):
    """Deterministic fake embeddings; the value depends only on the input."""

    def __init__(self):
        self.calls = []

    @staticmethod
    def name() -> str:
        return "default"

    def __call__(self, input: Documents) -> Embeddings:  # pylint: disable=redefined-builtin
        self.calls.append(list(input))
        vectors: list = []
        for text in input:
            vectors.append([float(len(text)), 0.5, -1.0])
        return vectors


class _SwitchableEmbeddingFunction(EmbeddingFunction[Documents]):
    """Embedding function that can be switched to failing."""

    def __init__(self):
        self.calls = []
        self.fail = False

    @staticmethod
    def name() -> str:
        return "default"

    def __call__(self, input: Documents) -> Embeddings:  # pylint: disable=redefined-builtin
        self.calls.append(list(input))
        if self.fail:
            raise RuntimeError("model exploded")
        vectors: list = []
        for _text in input:
            vectors.append([0.25, 0.75, 1.0])
        return vectors


def _initialize(tmp_path, embedding_function):
    with patch.object(
        chroma, "_get_embedding_function", return_value=embedding_function
    ):
        return chroma.initialize(_repository(tmp_path))


def _initialize_mocked(tmp_path, embedding_function, collection=None):
    collection = collection or MagicMock()
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    with (
        patch.object(chroma.chromadb, "PersistentClient", return_value=client),
        patch.object(
            chroma, "_get_embedding_function", return_value=embedding_function
        ),
    ):
        sources = chroma.initialize(_repository(tmp_path))
    return sources, collection


def _open_collection(tmp_path):
    cache_folder = Cache("chroma", Path(tmp_path), {}).get_cache_folder()
    client = chromadb.PersistentClient(
        path=str(cache_folder),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_collection("code_data")


def test_cache_batch_stores_partial_batch_immediately_with_metadata(tmp_path):
    embedding_function = _DeterministicEmbeddingFunction()
    sources = _initialize(tmp_path, embedding_function)
    chunks = [
        _chunk("id-1", "apple pie"),
        _chunk("id-2", "banana bread", codeline=42, path="dir/notes.txt"),
        _chunk("id-3", "cherry cake", codeline=7, object_id="obj-3"),
    ]

    sources["cache_batch"](chunks)

    stored = _open_collection(tmp_path).get(
        ids=["id-1", "id-2", "id-3"], include=["documents", "metadatas"]
    )
    documents_by_id = {
        cid: document for cid, document in zip(stored["ids"], stored["documents"] or [])
    }
    metadata_by_id = {
        cid: metadata for cid, metadata in zip(stored["ids"], stored["metadatas"] or [])
    }
    assert documents_by_id == {
        "id-1": "apple pie",
        "id-2": "banana bread",
        "id-3": "cherry cake",
    }
    assert metadata_by_id["id-1"] == {
        "path": "recipes.txt",
        "line": 3,
        "git_object_id": "deadbeef",
    }
    assert metadata_by_id["id-2"]["path"] == "dir/notes.txt"
    assert metadata_by_id["id-2"]["line"] == 42
    assert metadata_by_id["id-3"]["git_object_id"] == "obj-3"


def test_cache_batch_empty_is_noop(tmp_path):
    embedding_function = _DeterministicEmbeddingFunction()
    sources = _initialize(tmp_path, embedding_function)

    sources["cache_batch"]([])

    assert embedding_function.calls == []
    assert sources["indexed_ids"](["id-1"]) == set()


def test_cache_chunk_stores_single_chunk_immediately(tmp_path):
    embedding_function = _DeterministicEmbeddingFunction()
    sources = _initialize(tmp_path, embedding_function)

    sources["cache_chunk"](_chunk("solo", "only chunk"))

    assert len(embedding_function.calls) == 1
    assert sources["indexed_ids"](["solo"]) == {"solo"}


def test_cache_batch_embedding_failure_is_typed_as_embedding_error(tmp_path):
    embedding_function = _SwitchableEmbeddingFunction()
    sources = _initialize(tmp_path, embedding_function)

    embedding_function.fail = True
    with pytest.raises(chroma.EmbeddingError) as excinfo:
        sources["cache_batch"]([_chunk("bad", "never stored")])

    assert isinstance(excinfo.value, RuntimeError)
    assert "model exploded" in str(excinfo.value)
    assert sources["indexed_ids"](["bad"]) == set()


def test_failed_batch_leaves_no_residual_buffer(tmp_path):
    embedding_function = _SwitchableEmbeddingFunction()
    sources = _initialize(tmp_path, embedding_function)

    embedding_function.fail = True
    with pytest.raises(chroma.EmbeddingError):
        sources["cache_batch"]([_chunk("doomed", "never stored")])

    embedding_function.fail = False
    sources["cache_batch"]([_chunk("kept", "stored later")])

    assert sources["indexed_ids"](["doomed", "kept"]) == {"kept"}


def test_cache_batch_storage_failure_is_not_embedding_error(tmp_path):
    embedding_function = _DeterministicEmbeddingFunction()
    collection = MagicMock()
    collection.upsert.side_effect = RuntimeError("disk full")
    sources, _ = _initialize_mocked(tmp_path, embedding_function, collection)

    with pytest.raises(RuntimeError, match="disk full") as excinfo:
        sources["cache_batch"]([_chunk("id-1", "hello")])

    assert not isinstance(excinfo.value, chroma.EmbeddingError)
    assert len(embedding_function.calls) == 1


def test_probe_embedding_embeds_one_short_probe_without_storing(tmp_path):
    embedding_function = _DeterministicEmbeddingFunction()
    sources = _initialize(tmp_path, embedding_function)

    sources["probe_embedding"]()

    assert len(embedding_function.calls) == 1
    assert len(embedding_function.calls[0]) == 1
    assert len(embedding_function.calls[0][0]) < 100
    assert sources["indexed_ids"](["not-indexed"]) == set()


def test_failing_probe_embedding_raises_and_writes_nothing(tmp_path):
    embedding_function = _SwitchableEmbeddingFunction()
    sources = _initialize(tmp_path, embedding_function)

    embedding_function.fail = True
    with pytest.raises(chroma.EmbeddingError, match="model exploded"):
        sources["probe_embedding"]()

    assert len(embedding_function.calls) == 1
    assert sources["indexed_ids"](["not-indexed"]) == set()


def test_indexed_ids_empty_input_makes_no_chroma_call(tmp_path):
    embedding_function = _DeterministicEmbeddingFunction()
    sources, collection = _initialize_mocked(tmp_path, embedding_function)

    assert sources["indexed_ids"]([]) == set()
    collection.get.assert_not_called()


def test_indexed_ids_pages_lookups_in_pages_of_at_most_1000(tmp_path):
    embedding_function = _DeterministicEmbeddingFunction()
    collection = MagicMock()
    collection.get.side_effect = lambda ids, include: {"ids": list(ids)}
    sources, collection = _initialize_mocked(tmp_path, embedding_function, collection)
    ids = [f"id-{i}" for i in range(2500)]

    assert sources["indexed_ids"](ids) == set(ids)

    page_sizes = [len(call.kwargs["ids"]) for call in collection.get.call_args_list]
    assert page_sizes == [1000, 1000, 500]
    for call in collection.get.call_args_list:
        assert call.kwargs["include"] == []


def test_indexed_ids_finds_existing_ids_and_skips_missing(tmp_path):
    embedding_function = _DeterministicEmbeddingFunction()
    sources = _initialize(tmp_path, embedding_function)
    sources["cache_batch"]([_chunk("a", "aaa"), _chunk("b", "bbb"), _chunk("c", "ccc")])

    result = sources["indexed_ids"](["a", "missing", "c", "b", "missing2"])

    assert result == {"a", "b", "c"}
    assert isinstance(result, set)


def test_indexed_ids_propagates_read_errors(tmp_path):
    embedding_function = _DeterministicEmbeddingFunction()
    collection = MagicMock()
    collection.get.side_effect = RuntimeError("chroma is down")
    sources, _ = _initialize_mocked(tmp_path, embedding_function, collection)

    with pytest.raises(RuntimeError, match="chroma is down"):
        sources["indexed_ids"](["id-1"])
