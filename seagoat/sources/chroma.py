import importlib
import json
import os
import threading
from functools import cached_property
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import chromadb
from chromadb.api.types import (
    Documents,
    Embeddable,
    EmbeddingFunction,
    Embeddings,
    Metadata,
)
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

from seagoat.cache import Cache
from seagoat.repository import Repository
from seagoat.result import Result
from seagoat.utils.config import get_config_values

# One embedding function instance is built per process and embedding key and
# shared by all projects. Each key gets one instance per role: "index" for
# batch writes and probes, "query" for search text embedding. Indexing and
# queries use different instances, so one lane never waits for the other.
_INDEX_ROLE = "index"
_QUERY_ROLE = "query"

_EMBEDDING_FUNCTION_LOCK = threading.Lock()
_EMBEDDING_FUNCTIONS = {}  # (embedding_key, role) -> embedding function
_EMBEDDING_LOCKS = {}  # (embedding_key, role) -> lock serializing its calls

# The built-in ONNX model uses every CPU core while embedding. The indexing
# instance is capped to half the cores so queries keep the rest for
# themselves instead of competing with the indexing lane for CPU.
_INDEXING_ONNX_INTRA_OP_THREADS = max(1, (os.cpu_count() or 2) // 2)

# ONNXMiniLM_L6_V2._download_model_if_not_exists has no lock of its own:
# the first model load of the two instances must not run at the same time,
# or both may download and unpack into the same folder and corrupt
# model.onnx.
_MODEL_LOAD_LOCK = threading.Lock()


class EmbeddingError(RuntimeError):
    """Raised when the configured embedding function itself fails.

    Storage/upsert errors are deliberately NOT wrapped in this type, so the
    indexing worker can recover from them separately.
    """


# The probe embedded by probe_embedding(); its value is discarded, only the
# fact that embedding works matters.
_PROBE_TEXT = "probe"

# indexed_ids reads collection.get() in pages of at most this many ids.
_GET_PAGE_SIZE = 1000


class _LockedDownloadONNXMiniLM(ONNXMiniLM_L6_V2):
    """ONNXMiniLM_L6_V2 whose model download never overlaps another one.

    The original downloads and unpacks the model on its first call (not in
    its constructor), into a folder shared by all instances, with no lock of
    its own. Overlapping downloads can leave a truncated model.onnx that is
    never downloaded again.
    """

    _model_files_ready = False

    def _download_model_if_not_exists(self) -> None:
        if self._model_files_ready:
            return
        with _MODEL_LOAD_LOCK:
            super()._download_model_if_not_exists()
        self._model_files_ready = True


class _ThreadLimitedONNXMiniLM(_LockedDownloadONNXMiniLM):
    """ONNXMiniLM_L6_V2 with a capped intra-op thread count.

    chromadb's class has no option for the thread count: its ``model`` is a
    cached_property that builds the onnxruntime InferenceSession itself. This
    subclass rebuilds that property with the same providers logic and one
    extra SessionOptions setting (same logic as chromadb 1.5.9).
    """

    @cached_property
    def model(self):
        if self._preferred_providers is None or len(self._preferred_providers) == 0:
            self._preferred_providers = self.ort.get_available_providers()
        elif not set(self._preferred_providers).issubset(
            set(self.ort.get_available_providers())
        ):
            raise ValueError(
                "Preferred providers must be subset of available providers: "
                f"{self.ort.get_available_providers()}"
            )

        # Suppress onnxruntime warnings
        so = self.ort.SessionOptions()
        so.log_severity_level = 3
        so.graph_optimization_level = self.ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.intra_op_num_threads = _INDEXING_ONNX_INTRA_OP_THREADS

        providers = self._preferred_providers
        if providers and "CoreMLExecutionProvider" in providers:
            # remove CoreMLExecutionProvider from the list, it is not as
            # well optimized as CPU.
            providers = [p for p in providers if p != "CoreMLExecutionProvider"]

        return self.ort.InferenceSession(
            os.path.join(self.DOWNLOAD_PATH, self.EXTRACTED_FOLDER_NAME, "model.onnx"),
            # Since 1.9 onnx runtime requires providers to be specified when
            # there are multiple available
            providers=providers,
            sess_options=so,
        )


class _DefaultEmbeddingFunction(EmbeddingFunction[Documents]):
    """chromadb's DefaultEmbeddingFunction, but with one loaded model.

    The original builds a new ONNXMiniLM_L6_V2, and so loads the ONNX model
    again, on every call: once per batch of chunks while indexing.

    This is deliberately not a subclass of DefaultEmbeddingFunction: chromadb
    ignores any embedding function that is an instance of it, and builds a
    fresh default one from the collection config instead. It has the same
    name and config, so collections created with the original still open.
    """

    def __init__(self, model_class=None) -> None:
        self._model = None
        self._model_class = model_class

    # chromadb requires this exact parameter name
    def __call__(self, input: Documents) -> Embeddings:  # pylint: disable=redefined-builtin
        if self._model is None:
            self._model = (self._model_class or _LockedDownloadONNXMiniLM)()
        return self._model(input)

    @staticmethod
    def name() -> str:
        return embedding_functions.DefaultEmbeddingFunction.name()

    def get_config(self) -> dict[str, Any]:
        return {}

    def max_tokens(self) -> int:
        return 256

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "_DefaultEmbeddingFunction":
        return _DefaultEmbeddingFunction()

    @staticmethod
    def validate_config(config: dict[str, Any]) -> None:
        return


def for_collection(function: Any) -> EmbeddingFunction[Embeddable]:
    """Type an embedding function for chromadb's collection API.

    chromadb types that API for EmbeddingFunction[Embeddable], but text
    embedding functions (its own included) are EmbeddingFunction[Documents].
    """
    return cast(EmbeddingFunction[Embeddable], function)


def embedding_resource_key(config) -> tuple[str, str]:
    """Identity of the shared embedding resource a project's config selects.

    Projects whose configs produce the same key share one embedding function
    instance, so they also share its outage/probe/retry state in the global
    indexing scheduler. The name and arguments are global-only config.
    """
    embedding_function = config["server"]["chroma"]["embeddingFunction"]
    return (
        embedding_function["name"],
        json.dumps(embedding_function["arguments"], sort_keys=True, default=str),
    )


def chunk_metadata(chunk) -> Metadata:
    """The Chroma metadata stored for one chunk."""
    return {
        "path": chunk.path,
        "line": chunk.codeline,
        "git_object_id": chunk.object_id,
    }


def _get_embedding_function(config, role=_INDEX_ROLE) -> Any:
    """One embedding function instance per (config embedding key, role).

    The indexing instance (role "index") embeds batches and probes; the
    query instance (role "query") embeds search texts. Each instance is
    built lazily the first time it is needed and shared by all projects
    whose configs produce the same key.
    """
    embedding_function = config["server"]["chroma"]["embeddingFunction"]
    name = embedding_function["name"]
    arguments = embedding_function["arguments"]
    key = (embedding_resource_key(config), role)
    with _EMBEDDING_FUNCTION_LOCK:
        function = _EMBEDDING_FUNCTIONS.get(key)
        if function is None:
            if name == "DefaultEmbeddingFunction":
                if role == _INDEX_ROLE:
                    # The indexing instance shares the CPU with queries: cap
                    # its ONNX threads so queries keep cores free.
                    function = _DefaultEmbeddingFunction(
                        model_class=_ThreadLimitedONNXMiniLM
                    )
                else:
                    function = _DefaultEmbeddingFunction()
            elif ":" in name:
                module_path, class_name = name.split(":", 1)
                module = importlib.import_module(module_path)
                function = getattr(module, class_name)(**arguments)
            else:
                function_class = getattr(embedding_functions, name)
                if function_class is ONNXMiniLM_L6_V2:
                    # The same model as the default: same download lock, and
                    # the same thread cap for indexing
                    function_class = (
                        _ThreadLimitedONNXMiniLM
                        if role == _INDEX_ROLE
                        else _LockedDownloadONNXMiniLM
                    )
                function = function_class(**arguments)
            _EMBEDDING_FUNCTIONS[key] = function
        return function


def _get_embedding_lock(config, role=_INDEX_ROLE):
    """The lock serializing calls to one embedding function instance.

    User-configured embedding functions are not known to be thread-safe, so
    calls to the same instance take turns. Indexing and queries use
    different instances, so they never wait for each other. Some functions
    share one model between instances (SentenceTransformerEmbeddingFunction
    keeps one per model name), so that model can still run on both threads
    at once.
    """
    key = (embedding_resource_key(config), role)
    with _EMBEDDING_FUNCTION_LOCK:
        lock = _EMBEDDING_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _EMBEDDING_LOCKS[key] = lock
        return lock


def get_metadata_and_distance_from_chromadb_result(chromadb_results):
    return (
        list(
            zip(
                chromadb_results["metadatas"][0],
                chromadb_results["distances"][0],
            )
        )
        if chromadb_results["metadatas"] and chromadb_results["distances"]
        else None
    ) or []


def format_results(query_text: str, snapshot, chromadb_results, config):
    """Turn raw Chroma rows into results, using only the given repository
    snapshot: a row is current only if its file is, in the snapshot's HEAD,
    exactly the object it was indexed from."""
    files = {}
    max_vector_distance = config["server"]["chroma"]["maxVectorDistance"]

    for metadata, distance in get_metadata_and_distance_from_chromadb_result(
        chromadb_results
    ):
        if distance > max_vector_distance:
            break
        path = str(metadata["path"])
        line = int(metadata["line"])
        git_object_id = str(metadata["git_object_id"])

        # Files that are not part of the snapshot (deleted from the working
        # tree, ignored, unsupported) and stale vectors are skipped
        if not snapshot.has_file(path):
            continue

        if not snapshot.is_up_to_date_git_object(path, git_object_id):
            continue

        if path not in files:
            files[path] = Result(query_text, snapshot.get_file(path))
        files[path].add_vector_line(line, distance)

    return list(files.values())


def initialize(repository: Repository):
    # Chroma's Rust HNSW runtime creates one Tokio worker thread per CPU by
    # default, which on machines with many cores can push SeaGOAT over the
    # process's thread limit. Cap it to a small default unless the user
    # chose their own value (setdefault never overwrites an explicit
    # override). Must happen before PersistentClient builds that runtime.
    os.environ.setdefault("TOKIO_WORKER_THREADS", "2")

    cache = Cache("chroma", Path(repository.path), {})
    config = get_config_values(Path(repository.path))

    chroma_client = chromadb.PersistentClient(
        path=str(cache.get_cache_folder()),
        settings=Settings(
            anonymized_telemetry=False,
        ),
    )
    embedding_function = _get_embedding_function(config, _INDEX_ROLE)
    embedding_lock = _get_embedding_lock(config, _INDEX_ROLE)
    query_embedding_function = _get_embedding_function(config, _QUERY_ROLE)
    query_embedding_lock = _get_embedding_lock(config, _QUERY_ROLE)
    chroma_collection = chroma_client.get_or_create_collection(
        name="code_data",
        embedding_function=for_collection(embedding_function),
        # A high ef_search makes the approximate HNSW search close to exact,
        # so results do not depend on the order in which chunks were added
        configuration={"hnsw": {"ef_search": 1000}},
    )

    def _embed_with(embedding_function, lock, documents):
        with lock:
            try:
                return embedding_function(documents)
            except Exception as exc:
                raise EmbeddingError(
                    f"Embedding failed for {len(documents)} documents: {exc}"
                ) from exc

    def _embed(documents):
        return _embed_with(embedding_function, embedding_lock, documents)

    def write_batch(ids, documents, metadatas):
        """Embed and upsert a self-contained batch.

        Takes plain values only (no chunk objects, no repository), so the
        global indexing scheduler can run it from its own thread.
        """
        ids = list(ids)
        if not ids:
            return
        documents = list(documents)
        metadatas = cast(list[Metadata], list(metadatas))
        embeddings = _embed(documents)
        # Upsert errors are not wrapped in EmbeddingError: the indexing
        # worker must be able to tell embedding problems from storage
        # problems to pick the right recovery strategy.
        chroma_collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def cache_batch(chunks):
        chunks = list(chunks)
        write_batch(
            [chunk.chunk_id for chunk in chunks],
            [chunk.chunk for chunk in chunks],
            [chunk_metadata(chunk) for chunk in chunks],
        )

    def fetch_in_snapshot(query_text: str, limit: int, query_snapshot):
        # Slightly overfetch results as it will sorted using a different score later
        max_chunks_to_fetch = config["server"]["chroma"]["maxChunksToFetch"]
        n_results_multiplier = config["server"]["chroma"]["nResultsMultiplier"]
        n_results = min(int((limit + 1) * n_results_multiplier), max_chunks_to_fetch)

        # Embed with the query lane's instance, then search with the
        # precomputed embedding: passing query_texts would make chromadb
        # embed with the collection's (indexing) function instead.
        query_embedding = _embed_with(
            query_embedding_function, query_embedding_lock, [query_text]
        )

        chromadb_results = chroma_collection.query(
            query_embeddings=[query_embedding[0]],
            n_results=n_results,
        )

        return format_results(
            query_text, query_snapshot.repository, chromadb_results, config
        )

    def fetch(query_text: str, limit: int):
        # Standalone use: read the repository's currently published snapshot
        return fetch_in_snapshot(
            query_text, limit, SimpleNamespace(repository=repository.snapshot)
        )

    def probe_embedding():
        _embed([_PROBE_TEXT])

    def indexed_ids(ids: list[str]) -> set[str]:
        ids = list(ids)
        if not ids:
            return set()
        indexed: set[str] = set()
        for start in range(0, len(ids), _GET_PAGE_SIZE):
            page = ids[start : start + _GET_PAGE_SIZE]
            result = chroma_collection.get(ids=page, include=[])
            indexed.update(result["ids"])
        return indexed

    def all_ids() -> set[str]:
        """Enumerate every stored row ID in bounded pages.

        Uses a stable offset walk; offsets are only safe here because the
        engine snapshots candidates before any deletion happens elsewhere.
        """
        stored: set[str] = set()
        offset = 0
        while True:
            result = chroma_collection.get(
                include=[], limit=_GET_PAGE_SIZE, offset=offset
            )
            page = result["ids"]
            if not page:
                return stored
            stored.update(page)
            offset += len(page)
            if len(page) < _GET_PAGE_SIZE:
                return stored

    def delete_ids(ids: list[str]) -> None:
        """Delete rows in bounded pages; storage errors propagate for retry."""
        ids = list(ids)
        if not ids:
            return
        for start in range(0, len(ids), _GET_PAGE_SIZE):
            page = ids[start : start + _GET_PAGE_SIZE]
            chroma_collection.delete(ids=page)

    def cache_repo():
        # chromadb does not need any repo cache action
        pass

    return {
        "fetch": fetch,
        "fetch_in_snapshot": fetch_in_snapshot,
        "cache_batch": cache_batch,
        "write_batch": write_batch,
        "probe_embedding": probe_embedding,
        "indexed_ids": indexed_ids,
        "all_ids": all_ids,
        "delete_ids": delete_ids,
        "cache_repo": cache_repo,
    }
