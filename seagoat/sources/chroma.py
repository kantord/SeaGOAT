import importlib
import json
import threading
from pathlib import Path
from typing import Any, cast

import chromadb
from chromadb.api.types import Documents, Embeddable, EmbeddingFunction, Embeddings
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from seagoat.cache import Cache
from seagoat.repository import Repository
from seagoat.result import Result
from seagoat.utils.config import get_config_values

# One embedding function is built per process, lazily the first time it is
# needed, and shared by all projects. The name and arguments are a
# global-only config key, so one instance has one, but tests set different
# ones. The lock makes sure two projects starting at once build it once.
_EMBEDDING_FUNCTION_LOCK = threading.Lock()
_EMBEDDING_FUNCTIONS = {}

# The shared embedding function's tokenizer changes state on every call,
# so embedding calls take turns; that also caps how much CPU the projects
# use together.
_EMBEDDING_LOCK = threading.Lock()


class _DefaultEmbeddingFunction(EmbeddingFunction[Documents]):
    """chromadb's DefaultEmbeddingFunction, but with one loaded model.

    The original builds a new ONNXMiniLM_L6_V2, and so loads the ONNX model
    again, on every call: once per batch of chunks while indexing.

    This is deliberately not a subclass of DefaultEmbeddingFunction: chromadb
    ignores any embedding function that is an instance of it, and builds a
    fresh default one from the collection config instead. It has the same
    name and config, so collections created with the original still open.
    """

    def __init__(self) -> None:
        self._model = None

    # chromadb requires this exact parameter name
    def __call__(self, input: Documents) -> Embeddings:  # pylint: disable=redefined-builtin
        if self._model is None:
            from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
                ONNXMiniLM_L6_V2,
            )

            self._model = ONNXMiniLM_L6_V2()
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


# Built-in names that seagoat replaces with its own implementation
_EMBEDDING_FUNCTION_OVERRIDES = {"DefaultEmbeddingFunction": _DefaultEmbeddingFunction}


def _get_embedding_function(config):
    embedding_function = config["server"]["chroma"]["embeddingFunction"]
    name = embedding_function["name"]
    arguments = embedding_function["arguments"]
    key = (
        name,
        json.dumps(arguments, sort_keys=True, default=str),
    )
    with _EMBEDDING_FUNCTION_LOCK:
        function = _EMBEDDING_FUNCTIONS.get(key)
        if function is None:
            if ":" in name:
                module_path, class_name = name.split(":", 1)
                module = importlib.import_module(module_path)
                function = getattr(module, class_name)(**arguments)
            else:
                function_class = _EMBEDDING_FUNCTION_OVERRIDES.get(name) or getattr(
                    embedding_functions, name
                )
                function = function_class(**arguments)
            _EMBEDDING_FUNCTIONS[key] = function
        return function


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


def format_results(query_text: str, repository, chromadb_results, config):
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
        full_path = Path(repository.path) / path

        if not full_path.exists():
            continue

        if not repository.is_up_to_date_git_object(path, git_object_id):
            continue

        gitfile = repository.get_file(path)

        if path not in files:
            files[path] = Result(query_text, gitfile)
        files[path].add_line(line, distance)

    return files.values()


def initialize(repository: Repository):
    cache = Cache("chroma", Path(repository.path), {})
    config = get_config_values(Path(repository.path))

    chroma_client = chromadb.PersistentClient(
        path=str(cache.get_cache_folder()),
        settings=Settings(
            anonymized_telemetry=False,
        ),
    )
    embedding_function = _get_embedding_function(config)
    chroma_collection = chroma_client.get_or_create_collection(
        name="code_data",
        embedding_function=for_collection(embedding_function),
        # A high ef_search makes the approximate HNSW search close to exact,
        # so results do not depend on the order in which chunks were added
        configuration={"hnsw": {"ef_search": 1000}},
    )

    batch_size = config["server"]["chroma"]["batchSize"]
    batch_buffer = {"ids": [], "documents": [], "metadatas": []}

    def _flush_batch():
        if not batch_buffer["ids"]:
            return
        with _EMBEDDING_LOCK:
            chroma_collection.upsert(
                ids=batch_buffer["ids"],
                documents=batch_buffer["documents"],
                metadatas=batch_buffer["metadatas"],
            )
        batch_buffer["ids"].clear()
        batch_buffer["documents"].clear()
        batch_buffer["metadatas"].clear()

    def fetch(query_text: str, limit: int):
        # Slightly overfetch results as it will sorted using a different score later
        max_chunks_to_fetch = config["server"]["chroma"]["maxChunksToFetch"]
        n_results_multiplier = config["server"]["chroma"]["nResultsMultiplier"]
        n_results = min(int((limit + 1) * n_results_multiplier), max_chunks_to_fetch)

        with _EMBEDDING_LOCK:
            chromadb_results = chroma_collection.query(
                query_texts=[query_text],
                n_results=n_results,
            )

        return format_results(query_text, repository, chromadb_results, config)

    def cache_chunk(chunk):
        batch_buffer["ids"].append(chunk.chunk_id)
        batch_buffer["documents"].append(chunk.chunk)
        batch_buffer["metadatas"].append(
            {
                "path": chunk.path,
                "line": chunk.codeline,
                "git_object_id": chunk.object_id,
            }
        )
        if len(batch_buffer["ids"]) >= batch_size:
            _flush_batch()

    def cache_repo():
        # chromadb does not need any repo cache action
        pass

    return {
        "fetch": fetch,
        "cache_chunk": cache_chunk,
        "cache_repo": cache_repo,
        "flush_batch": _flush_batch,
    }
