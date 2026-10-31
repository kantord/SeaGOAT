"""Search result ordering must be robust to tiny embedding differences.

Different CPUs can produce embeddings that differ by a few ULPs in the last
place. Index the made-up project with a cached embedding function that
perturbs every vector by such a tiny, deterministic amount, and check that
each query returns the same files in the same order as the un-noisy
``realistic_engine``.
"""

import pytest

from seagoat.engine import Engine
from tests.fixtures.realistic_repo import SAMPLE_QUERIES, build


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_search_result_order_is_robust_to_embedding_noise(
    seed, tmp_path, create_config_file, realistic_engine
):
    repo_path = str(tmp_path / "repo")
    build(repo_path)

    create_config_file(
        {
            "server": {
                "chroma": {
                    "embeddingFunction": {
                        "name": (
                            "tests.fixtures.embedding_cache:"
                            "NoisyCachedEmbeddingFunction"
                        ),
                        "arguments": {"seed": seed},
                    }
                }
            }
        },
        global_config=True,
    )

    engine = Engine(repo_path)
    engine.analyze_codebase(minimum_chunks_to_analyze=351)
    assert engine.cache.data["chunks_not_yet_analyzed"] == set()

    for query in SAMPLE_QUERIES:
        expected = [
            result.gitfile.path for result in realistic_engine.query_sync(query)
        ]
        actual = [result.gitfile.path for result in engine.query_sync(query)]

        assert actual == expected
