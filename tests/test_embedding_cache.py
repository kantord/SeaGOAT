import os

import numpy as np

from tests.fixtures.embedding_cache import CachedEmbeddingFunction


def _vector(value: float) -> np.ndarray:
    return np.full(384, value, dtype=np.float32)


def test_hits_and_misses_keep_the_order_of_the_input(tmp_path, monkeypatch):
    monkeypatch.setenv("SEAGOAT_EMBEDDING_CACHE_LOG", str(tmp_path))
    function = CachedEmbeddingFunction()
    function._vectors = np.stack([_vector(1.0)])
    function._index = {function._key_for("cached"): 0}
    function._model = lambda texts: [
        _vector(2.0) if text == "a" else _vector(3.0) for text in texts
    ]

    vectors = function(["a", "cached", "b"])

    assert [float(vector[0]) for vector in vectors] == [2.0, 1.0, 3.0]
    assert len((tmp_path / f"{os.getpid()}.jsonl").read_text().splitlines()) == 2
