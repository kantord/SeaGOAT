"""Regression tests for SeaGOAT's default TOKIO_WORKER_THREADS cap.

Chroma's Rust HNSW index creates one Tokio worker thread per CPU by default;
on machines with many cores that can push a single SeaGOAT process over its
thread limit. SeaGOAT therefore sets a default of two Tokio workers before it
constructs its PersistentClient, without ever overwriting an explicit user
value (setdefault). The server and the direct library API share the same
source initializer (chroma.initialize), so covering it covers both.
"""

import os
import subprocess
import sys
from textwrap import dedent
from unittest.mock import MagicMock, patch

from seagoat.repository import Repository
from seagoat.sources import chroma

DEFAULT_TOKIO_WORKER_THREADS = "2"
EXPLICIT_TOKIO_WORKER_THREADS = "7"


def _recording_client_factory():
    """A PersistentClient stand-in that records the env value at call time.

    Recording inside the factory, instead of reading os.environ afterwards,
    proves the default is in effect exactly when the client is created.

    Returns the factory and the list it appends to.
    """
    observed = []

    def client_factory(*args, **kwargs):
        observed.append(os.environ.get("TOKIO_WORKER_THREADS"))
        return MagicMock()

    return client_factory, observed


def _initialize_with_client_factory(repo, client_factory):
    """Run chroma.initialize with chromadb.PersistentClient replaced.

    The embedding function is mocked too, so the test checks the runtime
    setting without constructing or loading any embedding model.
    """
    repository = Repository(repo.working_dir)
    with (
        patch.object(chroma.chromadb, "PersistentClient", client_factory),
        patch.object(chroma, "_get_embedding_function", return_value=MagicMock()),
    ):
        chroma.initialize(repository)


def test_sets_default_tokio_worker_threads_before_client_factory(monkeypatch, repo):
    monkeypatch.delenv("TOKIO_WORKER_THREADS", raising=False)
    client_factory, observed = _recording_client_factory()

    _initialize_with_client_factory(repo, client_factory)

    assert observed == [DEFAULT_TOKIO_WORKER_THREADS]
    assert os.environ["TOKIO_WORKER_THREADS"] == DEFAULT_TOKIO_WORKER_THREADS


def test_preserves_explicit_tokio_worker_threads_override(monkeypatch, repo):
    monkeypatch.setenv("TOKIO_WORKER_THREADS", EXPLICIT_TOKIO_WORKER_THREADS)
    client_factory, observed = _recording_client_factory()

    _initialize_with_client_factory(repo, client_factory)

    assert observed == [EXPLICIT_TOKIO_WORKER_THREADS]
    assert os.environ["TOKIO_WORKER_THREADS"] == EXPLICIT_TOKIO_WORKER_THREADS


_SUBPROCESS_SCRIPT = dedent(
    """
    import os
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from seagoat.sources import chroma

    observed = []

    def client_factory(*args, **kwargs):
        observed.append(os.environ.get("TOKIO_WORKER_THREADS"))
        return MagicMock()

    repository = SimpleNamespace(path=Path(tempfile.mkdtemp()))
    with (
        patch.object(chroma.chromadb, "PersistentClient", client_factory),
        patch.object(chroma, "_get_embedding_function", return_value=MagicMock()),
    ):
        assert "TOKIO_WORKER_THREADS" not in os.environ
        chroma.initialize(repository)
        assert observed == ["2"]

        os.environ["TOKIO_WORKER_THREADS"] = "7"
        chroma.initialize(repository)
        assert observed == ["2", "7"]
    """
)


def test_default_and_override_apply_in_a_fresh_subprocess():
    env = os.environ.copy()
    env.pop("TOKIO_WORKER_THREADS", None)
    result = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_SCRIPT],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
