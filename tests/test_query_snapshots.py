"""Queries run against one coherent snapshot, which replacements never disturb.

The tests use explicit barriers/events instead of sleeps: a query is parked at a
known point of its life while the repository state is replaced around it.
"""

import os
import platform
import threading
from pathlib import Path

import pytest

from seagoat.cache import Cache
from seagoat.engine import Engine
from seagoat.repository import Repository
from seagoat.sources import chroma, ripgrep

TIMEOUT = 20


def _ripgrep_only_engine(repo) -> Engine:
    """An Engine with the real ripgrep source and no vector source.

    Chroma does not take part in snapshot publication (it has no per-snapshot
    state), so leaving it out keeps these tests deterministic and fast.
    """
    engine = Engine(repo.working_dir)
    engine._fetchers["sync"] = []
    return engine


def _ripgrep_source(engine: Engine) -> dict:
    return engine._fetchers["async"][0]


def _line_texts(results) -> dict[str, set[str]]:
    return {
        result.gitfile.path: {line.line_text for line in result.lines.values()}
        for result in results
    }


class _Query(threading.Thread):
    """Runs ``engine.query_sync`` on its own thread and keeps the outcome"""

    def __init__(self, engine, *args, **kwargs):
        super().__init__(daemon=True)
        self._engine, self._args, self._kwargs = engine, args, kwargs
        self.results = None
        self.error = None

    def run(self):
        try:
            self.results = self._engine.query_sync(*self._args, **self._kwargs)
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            self.error = exc

    def finish(self):
        self.join(TIMEOUT)
        assert not self.is_alive(), "query did not finish"
        if self.error is not None:
            raise self.error
        assert self.results is not None, "query returned no result list"
        return self.results


def _park_ripgrep_fetches(engine: Engine, parties: int = 1):
    """Make every ripgrep fetch wait at a barrier, then at a gate, before it
    reads anything. Returns (arrived, gate): ``arrived`` is set once ``parties``
    fetches are parked, and they continue when ``gate`` is set."""
    source = _ripgrep_source(engine)
    real_fetch = source["fetch_in_snapshot"]
    arrived = threading.Event()
    gate = threading.Event()
    counter = {"n": 0}
    lock = threading.Lock()

    def parked_fetch(query_text, limit, snapshot):
        with lock:
            counter["n"] += 1
            if counter["n"] >= parties:
                arrived.set()
        assert gate.wait(TIMEOUT), "gate never opened"
        return real_fetch(query_text, limit, snapshot)

    source["fetch_in_snapshot"] = parked_fetch
    return arrived, gate


def _track_ripgrep_indexes(engine: Engine) -> list:
    """Record every ripgrep index the engine builds"""
    source = _ripgrep_source(engine)
    real_build = source["build_state"]
    built = []

    def recording_build(snapshot):
        state = real_build(snapshot)
        built.append(state)
        return state

    source["build_state"] = recording_build
    return built


def test_simultaneous_queries_do_not_mix_results(repo):
    repo.add_file_change_commit("alpha.txt", "alphaword here\n", "Add alpha")
    repo.add_file_change_commit("beta.txt", "betaword here\n", "Add beta")
    engine = _ripgrep_only_engine(repo)
    engine.refresh_snapshot()
    # Both queries must be inside their fetch at the same time: with a shared
    # result list the second one's results would land in the first one's
    arrived, gate = _park_ripgrep_fetches(engine, parties=2)

    first = _Query(engine, "alphaword")
    second = _Query(engine, "betaword")
    first.start()
    second.start()
    assert arrived.wait(TIMEOUT)
    gate.set()

    assert [r.gitfile.path for r in first.finish()] == ["alpha.txt"]
    assert [r.gitfile.path for r in second.finish()] == ["beta.txt"]
    assert not hasattr(engine, "_results")


def test_query_spanning_replacement_reads_one_consistent_old_state(repo):
    repo.add_file_change_commit(
        "moving.txt", "oldword first\noldword second\noldword third\n", "Add moving"
    )
    engine = _ripgrep_only_engine(repo)
    engine.refresh_snapshot()
    indexes = _track_ripgrep_indexes(engine)
    arrived, gate = _park_ripgrep_fetches(engine)

    in_flight = _Query(engine, "oldword", context_below=1)
    in_flight.start()
    assert arrived.wait(TIMEOUT)

    # Replace everything while the query is parked inside its fetch
    repo.add_file_change_commit(
        "moving.txt", "newword first\nnewword second\nnewword third\n", "Rewrite"
    )
    engine.refresh_snapshot()
    (replacement,) = indexes
    gate.set()

    texts = _line_texts(in_flight.finish())
    # Matching lines and context lines all come from the old version
    assert texts == {"moving.txt": {"oldword first", "oldword second", "oldword third"}}

    # A later query sees the new state, and only the new state
    assert _line_texts(engine.query_sync("newword")) == {
        "moving.txt": {"newword first", "newword second", "newword third"}
    }
    assert engine.query_sync("oldword") == []
    assert not replacement.is_closed


def test_retired_snapshot_stays_open_until_its_last_reader_is_done(repo):
    engine = _ripgrep_only_engine(repo)
    first = engine.refresh_snapshot()
    reader = first.acquire()
    index = first.state_for(_ripgrep_source(engine))

    engine.refresh_snapshot()

    assert not index.is_closed, "an in-flight reader still needs it"
    assert reader.state_for(_ripgrep_source(engine)) is index
    reader.release()
    assert index.is_closed
    assert first.closed


def test_failed_discovery_keeps_the_last_usable_snapshot(repo, mocker):
    repo.add_file_change_commit("stable.txt", "stableword\n", "Add stable")
    engine = _ripgrep_only_engine(repo)
    published = engine.refresh_snapshot()
    indexes = _track_ripgrep_indexes(engine)

    mocker.patch.object(
        engine.repository, "_get_working_tree_files", side_effect=RuntimeError("rg")
    )
    with pytest.raises(RuntimeError, match="rg"):
        engine.refresh_snapshot()

    assert indexes == []
    assert engine._snapshot is published
    assert engine.repository.snapshot is published.repository
    assert list(_line_texts(engine.query_sync("stableword"))) == ["stable.txt"]


def test_failed_cache_construction_keeps_snapshot_and_releases_partial_state(
    repo, mocker
):
    repo.add_file_change_commit("stable.txt", "stableword\n", "Add stable")
    engine = _ripgrep_only_engine(repo)
    published = engine.refresh_snapshot()
    indexes = _track_ripgrep_indexes(engine)
    cache_folder = Cache("ripgrep", Path(repo.working_dir), {}).get_cache_folder()

    def failing_build(_snapshot):
        raise OSError("disk full")

    # A second source whose cache construction fails after ripgrep's succeeded
    engine._fetchers["sync"] = [{"build_state": failing_build}]
    with pytest.raises(OSError, match="disk full"):
        engine.refresh_snapshot()

    (abandoned,) = indexes
    assert abandoned.is_closed, "the unpublished replacement must be released"
    assert not list(cache_folder.glob("mmap.*"))
    assert engine._snapshot is published
    assert engine.repository.snapshot is published.repository
    engine._fetchers["sync"] = []
    assert list(_line_texts(engine.query_sync("stableword"))) == ["stable.txt"]


def test_failure_while_building_the_ripgrep_file_leaves_no_file(repo, mocker):
    engine = _ripgrep_only_engine(repo)
    published = engine.refresh_snapshot()
    cache_folder = Cache("ripgrep", Path(repo.working_dir), {}).get_cache_folder()
    mocker.patch.object(
        engine.repository, "get_blobs_data", side_effect=RuntimeError("git")
    )

    with pytest.raises(RuntimeError, match="git"):
        engine.refresh_snapshot()

    assert not list(cache_folder.glob("mmap.*"))
    assert engine._snapshot is published


def _open_files_in(folder: Path) -> int:
    """Count this process's descriptors and memory mappings of files in folder.

    Only files in the cache folder count: a process-wide descriptor count
    changes whenever objects left by earlier tests are garbage collected.
    """
    prefix = str(folder)
    descriptors = 0
    for name in os.listdir("/proc/self/fd"):
        try:
            target = os.readlink(f"/proc/self/fd/{name}")
        except OSError:  # closed between listing and reading
            continue
        descriptors += target.startswith(prefix)
    with open("/proc/self/maps", encoding="utf-8") as maps:
        mappings = sum(prefix in line for line in maps)
    return descriptors + mappings


def test_repeated_replacement_does_not_leak_mappings_or_files(repo):
    engine = _ripgrep_only_engine(repo)
    indexes = _track_ripgrep_indexes(engine)
    cache_folder = Cache("ripgrep", Path(repo.working_dir), {}).get_cache_folder()
    # The fixture's own commit machinery opens a few descriptors the first
    # times it is used; warm it up so only the code under test is measured
    for warmup in range(3):
        repo.add_file_change_commit("churn.txt", f"warmup {warmup}\n", "Warm up")
    engine.refresh_snapshot()
    on_linux = platform.system() == "Linux"
    open_files = _open_files_in(cache_folder) if on_linux else 0

    for round_number in range(8):
        repo.add_file_change_commit(
            "churn.txt", f"round {round_number}\n", f"Round {round_number}"
        )
        engine.refresh_snapshot()
        engine.query_sync("round")

    assert len(indexes) == 9
    assert [index.is_closed for index in indexes] == [True] * 8 + [False]
    assert not list(cache_folder.glob("mmap.*")), "no cache file may be left behind"
    if on_linux:
        assert _open_files_in(cache_folder) == open_files

    engine.close()
    assert all(index.is_closed for index in indexes)
    assert engine._snapshot is None


def test_replaced_mapping_is_never_rewritten_in_place(repo):
    repo.add_file_change_commit("moving.txt", "oldword\n", "Add")
    engine = _ripgrep_only_engine(repo)
    first = engine.refresh_snapshot()
    old_index = first.state_for(_ripgrep_source(engine))
    old_input = bytes(old_index.as_input())
    reader = first.acquire()

    repo.add_file_change_commit("moving.txt", "a much longer newword line\n", "Edit")
    second = engine.refresh_snapshot()

    new_index = second.state_for(_ripgrep_source(engine))
    assert new_index is not old_index
    assert b"oldword" in old_input
    assert bytes(old_index.as_input()) == old_input
    assert b"newword" in bytes(new_index.as_input())
    reader.release()
    assert old_index.is_closed


def test_scan_builds_a_snapshot_without_publishing_it(repo):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    published = repository.snapshot
    repo.add_file_change_commit("later.txt", "later\n", "Add later")

    scanned = repository.scan()

    assert repository.snapshot is published
    assert not published.has_file("later.txt")
    assert scanned.has_file("later.txt")
    assert scanned.object_ids["later.txt"] == scanned.get_file("later.txt").object_id


def test_query_without_a_published_snapshot_builds_the_first_one(repo):
    engine = _ripgrep_only_engine(repo)
    assert engine._snapshot is None

    assert engine.query_sync("example")

    assert engine._snapshot is not None


def test_stale_vectors_are_filtered_against_the_query_snapshot(repo):
    repository = Repository(repo.working_dir)
    snapshot = repository.scan()
    current_id = snapshot.object_ids["file2.py"]
    rows = {
        "metadatas": [
            [
                {"path": "file2.py", "line": 1, "git_object_id": current_id},
                {"path": "file2.py", "line": 1, "git_object_id": "0" * 40},
                {"path": "gone.py", "line": 1, "git_object_id": current_id},
            ]
        ],
        "distances": [[0.1, 0.2, 0.3]],
    }
    config = {"server": {"chroma": {"maxVectorDistance": 1.0}}}

    results = list(chroma.format_results("query", snapshot, rows, config))

    assert [(r.gitfile.path, sorted(r.lines)) for r in results] == [("file2.py", [1])]


def test_ripgrep_standalone_fetch_releases_replaced_indexes(repo):
    repository = Repository(repo.working_dir)
    repository.analyze_files()
    source = ripgrep.initialize(repository)

    source["cache_repo"]()
    source["fetch"]("example", 10)
    source["cache_repo"]()
    assert source["fetch"]("example", 10)
