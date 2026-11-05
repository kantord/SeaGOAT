import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
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


def _initialize_with_roles(
    tmp_path, index_embedding_function, query_embedding_function, collection=None
):
    """Like _initialize_mocked, but with a different embedding function per role."""
    collection = collection or MagicMock()
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    with (
        patch.object(chroma.chromadb, "PersistentClient", return_value=client),
        patch.object(
            chroma,
            "_get_embedding_function",
            side_effect=lambda config, role: {
                chroma._INDEX_ROLE: index_embedding_function,
                chroma._QUERY_ROLE: query_embedding_function,
            }[role],
        ),
    ):
        sources = chroma.initialize(_repository(tmp_path))
    return sources, collection


class _BlockingEmbeddingFunction(_DeterministicEmbeddingFunction):
    """Deterministic embedding function that blocks until released."""

    def __init__(self, started, release):
        super().__init__()
        self.started = started
        self.release = release

    def __call__(self, input: Documents) -> Embeddings:  # pylint: disable=redefined-builtin
        self.calls.append(list(input))
        self.started.set()
        if not self.release.wait(30):
            raise TimeoutError("indexing embedding was never released")
        return super().__call__(input)


def test_query_completes_while_indexing_embed_is_blocked(tmp_path):
    # A query must not wait for the indexing lane: the two roles embed with
    # different instances, so the blocked indexing embed cannot stall the
    # query even though it holds the indexing instance's lock.
    import threading

    release_indexing = threading.Event()
    indexing_started = threading.Event()
    index_fn = _BlockingEmbeddingFunction(indexing_started, release_indexing)
    query_fn = _DeterministicEmbeddingFunction()
    collection = MagicMock()
    collection.query.return_value = {"metadatas": None, "distances": None}
    sources, collection = _initialize_with_roles(
        tmp_path, index_fn, query_fn, collection
    )

    batch_thread = threading.Thread(
        target=sources["write_batch"],
        args=(
            ["id-1"],
            ["blocked chunk"],
            [{"path": "recipes.txt", "line": 3, "git_object_id": "deadbeef"}],
        ),
        daemon=True,
    )
    batch_thread.start()
    assert indexing_started.wait(5), "indexing batch never started embedding"

    try:
        results = sources["fetch_in_snapshot"](
            "query text", 10, SimpleNamespace(repository=MagicMock())
        )
        # The query ran to completion while the indexing embed was still blocked.
        assert results == []
    finally:
        release_indexing.set()
        batch_thread.join(5)
    assert not batch_thread.is_alive()


def test_two_roles_give_two_instances_for_the_same_config(tmp_path):
    import copy

    from seagoat.utils.config import DEFAULT_CONFIG

    config = copy.deepcopy(DEFAULT_CONFIG)
    index_instance1 = chroma._get_embedding_function(config, chroma._INDEX_ROLE)
    index_instance2 = chroma._get_embedding_function(config, chroma._INDEX_ROLE)
    query_instance1 = chroma._get_embedding_function(config, chroma._QUERY_ROLE)
    query_instance2 = chroma._get_embedding_function(config, chroma._QUERY_ROLE)

    assert index_instance1 is index_instance2
    assert query_instance1 is query_instance2
    assert index_instance1 is not query_instance1


class _RecordingSessionOptions:
    """SessionOptions stand-in that records which attributes were assigned."""

    intra_op_num_threads: int | None = None

    def __init__(self):
        self._assigned = set()

    def __setattr__(self, name, value):
        if not name.startswith("_"):
            self._assigned.add(name)
        super().__setattr__(name, value)


def test_indexing_instance_limits_onnx_threads_but_query_instance_does_not(tmp_path):
    import copy

    from seagoat.utils.config import DEFAULT_CONFIG

    config = copy.deepcopy(DEFAULT_CONFIG)
    index_fn = chroma._get_embedding_function(config, chroma._INDEX_ROLE)
    query_fn = chroma._get_embedding_function(config, chroma._QUERY_ROLE)
    assert index_fn._model_class is chroma._ThreadLimitedONNXMiniLM
    assert query_fn._model_class is None

    with (
        patch("onnxruntime.InferenceSession") as session_class,
        patch(
            "onnxruntime.SessionOptions",
            return_value=(index_so := _RecordingSessionOptions()),
        ),
    ):
        index_model = index_fn._model_class()
        _session = index_model.model
    assert session_class.call_args.kwargs["sess_options"] is index_so
    assert index_so.intra_op_num_threads == chroma._INDEXING_ONNX_INTRA_OP_THREADS
    assert "intra_op_num_threads" in index_so._assigned

    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
        ONNXMiniLM_L6_V2,
    )

    with (
        patch("onnxruntime.InferenceSession") as session_class,
        patch(
            "onnxruntime.SessionOptions",
            return_value=(query_so := _RecordingSessionOptions()),
        ),
    ):
        query_model = ONNXMiniLM_L6_V2()
        _session = query_model.model
    assert session_class.call_args.kwargs["sess_options"] is query_so
    assert "intra_op_num_threads" not in query_so._assigned


def test_query_passes_query_embeddings_not_query_texts(tmp_path):
    embedding_function = _DeterministicEmbeddingFunction()
    collection = MagicMock()
    collection.query.return_value = {"metadatas": None, "distances": None}
    sources, collection = _initialize_mocked(tmp_path, embedding_function, collection)

    results = sources["fetch_in_snapshot"](
        "cherry pie", 5, SimpleNamespace(repository=MagicMock())
    )
    assert results == []
    call_kwargs = collection.query.call_args.kwargs
    query_embeddings = call_kwargs["query_embeddings"]
    assert len(query_embeddings) == 1
    assert list(query_embeddings[0]) == [10.0, 0.5, -1.0]
    assert "query_texts" not in call_kwargs


class _DownloadingModel:
    """Stands in for ONNXMiniLM_L6_V2: its first call downloads and unpacks the model.

    Records how many first calls overlap, because chromadb's download writes the
    shared model folder without a lock of its own.
    """

    state: ClassVar[dict[str, int]] = {"downloading": 0, "peak": 0}
    lock = threading.Lock()

    def __init__(self):
        self.downloaded = False

    def __call__(self, input):  # pylint: disable=redefined-builtin
        if not self.downloaded:
            with self.lock:
                self.state["downloading"] += 1
                self.state["peak"] = max(self.state["peak"], self.state["downloading"])
            time.sleep(0.05)
            with self.lock:
                self.state["downloading"] -= 1
            self.downloaded = True
        return [[0.0, 1.0, 0.0] for _ in input]


def test_first_model_downloads_of_index_and_query_instances_do_not_overlap():
    _DownloadingModel.state.update(downloading=0, peak=0)
    instances = [
        chroma._DefaultEmbeddingFunction(model_class=_DownloadingModel)
        for _ in range(2)
    ]
    start = threading.Barrier(2)

    def first_call(function):
        start.wait()
        function(["hello"])

    threads = [threading.Thread(target=first_call, args=(f,)) for f in instances]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert _DownloadingModel.state["peak"] == 1
