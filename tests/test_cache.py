import tempfile
from pathlib import Path

import pytest

from seagoat.cache import Cache

REPO_PATH = Path("/some/repository")


@pytest.fixture
def isolated_cache_dir(monkeypatch, tmp_path):
    """Point SEAGOAT_CACHE_DIR at a per-test temporary directory."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("SEAGOAT_CACHE_DIR", str(cache_dir))
    return cache_dir


@pytest.fixture
def cache(isolated_cache_dir):
    return Cache("test-cache", REPO_PATH, {})


def _reload():
    reloaded = Cache("test-cache", REPO_PATH, {})
    reloaded.load()
    return reloaded


def _temp_files(cache):
    return list(cache.get_cache_folder().glob(".*.tmp"))


def test_round_trip(cache):
    cache.data = {"version": 1, "chunks": {"a", "b"}}
    cache.persist()

    assert _reload().data == {"version": 1, "chunks": {"a", "b"}}


def test_partial_serialization_failure_preserves_previous_data(cache, monkeypatch):
    cache.data = {"version": 1}
    cache.persist()

    def failing_dump(obj, file, *args, **kwargs):
        # Simulate a crash halfway through serialization: write partial bytes
        # then fail, so the naive in-place write would leave a corrupt cache.
        file.write(b"\x80\x04\x95partial")
        raise ValueError("serialization failed")

    monkeypatch.setattr("seagoat.cache.pickle.dump", failing_dump)

    cache.data = {"version": 2}
    with pytest.raises(ValueError):
        cache.persist()

    # Previously persisted data is intact and the temporary file is gone.
    assert _reload().data == {"version": 1}
    assert _temp_files(cache) == []


def test_replacement_failure_preserves_original_data(cache, monkeypatch):
    cache.data = {"version": 1}
    cache.persist()

    def failing_replace(src, dst):
        raise OSError("replacement failed")

    monkeypatch.setattr("seagoat.cache.os.replace", failing_replace)

    cache.data = {"version": 2}
    with pytest.raises(OSError):
        cache.persist()

    # Previously persisted data is intact and the temporary file is gone.
    assert _reload().data == {"version": 1}
    assert _temp_files(cache) == []


def test_temporary_files_are_cleaned_up_after_success(cache):
    cache.data = {"version": 1}
    cache.persist()
    cache.persist()

    assert _temp_files(cache) == []
    # The only file in the cache folder is the cache itself.
    assert sorted(entry.name for entry in cache.get_cache_folder().iterdir()) == [
        "test-cache"
    ]


def test_temporary_files_have_unique_names(cache, monkeypatch):
    created = []
    real_mkstemp = tempfile.mkstemp

    def recording_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        created.append(Path(name))
        return fd, name

    monkeypatch.setattr("seagoat.cache.tempfile.mkstemp", recording_mkstemp)

    cache.data = {"version": 1}
    cache.persist()
    cache.persist()

    # Each persist writes through its own uniquely named temporary file in the
    # same per-project directory as the final cache file.
    assert len(created) == 2
    assert created[0] != created[1]
    for temp_path in created:
        assert temp_path.parent == cache.get_cache_folder()
        assert temp_path.name != "test-cache"
    assert _temp_files(cache) == []
