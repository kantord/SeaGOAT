"""A cached ChromaDB embedding function for the test suite.

Stores embeddings for texts that appear in the tests in a committed
``embedding_cache.npz`` file so most tests never run the real ONNX
embedding model. The cache is selected through the global config file
(``server.chroma.embeddingFunction.name`` set to
``tests.fixtures.embedding_cache:CachedEmbeddingFunction``), so it also
applies to server subprocesses started by the tests.
"""

import hashlib
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

_CACHE_FILE = Path(__file__).parent / "embedding_cache.npz"
_MODEL_NAME = "all-MiniLM-L6-v2"
_DIMENSION = 384


class CachedEmbeddingFunction(EmbeddingFunction[Documents]):
    """Embedding function that serves vectors from a file-based cache.

    On a miss it computes the vector with a single lazily created
    ``ONNXMiniLM_L6_V2()`` instance (reused for every miss) and logs the
    miss to the directory named by the ``SEAGOAT_EMBEDDING_CACHE_LOG``
    environment variable, so a later run with ``--update-embedding-cache``
    can persist it.
    """

    def __init__(self) -> None:
        self._vectors: np.ndarray | None = None
        self._index: dict[str, int] = {}
        self._model: Callable[[Documents], Embeddings] | None = None
        self._lock = threading.Lock()

    def _load_cache(self) -> np.ndarray:
        with self._lock:
            if self._vectors is not None:
                return self._vectors
            if _CACHE_FILE.exists():
                data = np.load(_CACHE_FILE)
                keys, vectors = data["keys"], data["vectors"]
            else:
                keys, vectors = [], np.empty((0, _DIMENSION), dtype=np.float32)
            self._index = {str(key): i for i, key in enumerate(keys)}
            self._vectors = vectors
            return vectors

    def _get_model(self) -> Callable[[Documents], Embeddings]:
        if self._model is None:
            self._model = ONNXMiniLM_L6_V2()
        return self._model

    @staticmethod
    def _key_for(text: str) -> str:
        return hashlib.sha256(f"{_MODEL_NAME}\0{text}".encode()).hexdigest()

    def _log_miss(self, key: str, vector) -> None:
        log_dir = os.environ.get("SEAGOAT_EMBEDDING_CACHE_LOG")
        if not log_dir:
            return
        path = Path(log_dir) / f"{os.getpid()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as output:
            output.write(json.dumps([key, [float(value) for value in vector]]) + "\n")
            output.flush()

    def __call__(self, input: Documents) -> Embeddings:
        cached_vectors = self._load_cache()
        results: list = [None] * len(input)
        # (position in input, text, key) of every text not in the cache
        missing: list[tuple[int, str, str]] = []

        for position, text in enumerate(input):
            key = self._key_for(text)
            index = self._index.get(key)
            if index is not None:
                results[position] = cached_vectors[index]
            else:
                missing.append((position, text, key))

        if missing:
            vectors = self._get_model()([text for _, text, _ in missing])
            for (position, _, key), vector in zip(missing, vectors):
                self._log_miss(key, vector)
                results[position] = np.asarray(vector, dtype=np.float32)

        return results

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "CachedEmbeddingFunction":
        CachedEmbeddingFunction.validate_config(config)
        return CachedEmbeddingFunction()

    @staticmethod
    def name() -> str:
        return "cached_embedding"

    def get_config(self) -> dict[str, Any]:
        return {}

    def max_tokens(self) -> int:
        return 256

    @staticmethod
    def validate_config(config: dict[str, Any]) -> None:
        return
