"""Focused regression tests for stage H: plan/index/prune against real Chroma.

These tests are independent of the legacy acceptance suite and exercise the
corrected implementation directly (Engine + real local Chroma with a
deterministic fake embedding function). The queue tests drive TaskQueue
manually with an explicit context and a fake ``task_queue.time`` clock
(SimpleNamespace with both time and monotonic), so no real worker thread,
model download or sleep is involved.
"""

import subprocess
from pathlib import Path
from queue import PriorityQueue
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from seagoat.cache import Cache
from seagoat.engine import Engine
from seagoat.gitfile import GitFile
from seagoat.queue import task_queue
from seagoat.queue.base_queue import HIGH_PRIORITY, Task, TaskFailed
from seagoat.queue.task_queue import TaskQueue
from seagoat.repository import Repository
from seagoat.sources import chroma
from tests.fixtures.scheduling import attach_lane
from tests.test_chroma_batches import (
    _chunk,
    _DeterministicEmbeddingFunction,
    _open_collection,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_engine(repo_path, embedding_function=None):
    ef = embedding_function or _DeterministicEmbeddingFunction()
    with patch.object(chroma, "_get_embedding_function", return_value=ef):
        engine = Engine(repo_path)
    return engine, ef


def _index_all(engine):
    """Plan and embed everything in one Engine, through the public API."""
    pending = engine.plan_indexing()
    assert pending, "expected pending chunks in a fresh repository"
    batch_size = engine.config["server"]["chroma"]["batchSize"]
    for start in range(0, len(pending), batch_size):
        engine.process_batch(pending[start : start + batch_size])
    stats = engine.get_indexing_stats()
    assert stats["pending"] == 0
    assert stats["analyzed"] == stats["total"]
    while engine.pending_prune_count():
        assert engine.prune_stale() > 0
    assert engine.pending_prune_count() == 0


def _plant_rows(repo_path, count, embedding_function, prefix="ghost"):
    """Directly insert foreign rows into the same persistent collection."""
    with patch.object(
        chroma, "_get_embedding_function", return_value=embedding_function
    ):
        sources = chroma.initialize(Repository(repo_path))
    chunks = [
        _chunk(
            f"{prefix}-{idx}",
            f"orphan row number {idx} with plenty of words to embed",
            path=f"orphan-{prefix}-{idx}.txt",
        )
        for idx in range(count)
    ]
    sources["cache_batch"](chunks)


def _collection_ids(repo_path):
    return set(_open_collection(repo_path).get(include=[])["ids"])


def _current_row_paths(repo_path):
    rows = _open_collection(repo_path).get(include=["metadatas"])["metadatas"]
    assert rows is not None
    paths: set[str] = set()
    for row in rows:
        path = row["path"]
        assert isinstance(path, str)
        paths.add(path)
    return paths


def _commit_change(repo, path, content, message):
    repo.add_file_change_commit(path, content, message)


def _make_task_queue(engine):
    queue = TaskQueue.__new__(TaskQueue)
    queue.kwargs = {"repo_path": engine.path}
    queue._task_queue = PriorityQueue()
    context = {
        "seagoat_engine": engine,
        "last_maintenance": None,
        "last_repo_state_hash": None,
    }
    queue._ensure_recovery_state(context)
    attach_lane(queue, context)
    return queue, context


def _drive_next(queue, context):
    task = queue._task_queue.get()
    assert isinstance(task, Task)
    queue._handle_task(context, task)
    result_queue = task.kwargs.get("__result_queue")
    if result_queue is not None:
        assert not isinstance(result_queue.get_nowait(), TaskFailed)


# ---------------------------------------------------------------------------
# (1) restart / legacy cache never overrides Chroma existence
# ---------------------------------------------------------------------------


def test_restart_legacy_cache_never_overrides_actual_chroma(repo):
    engine, ef = _make_engine(repo.working_dir)
    _index_all(engine)

    current_ids = _collection_ids(repo.working_dir)
    assert current_ids
    regularly_present = sorted(current_ids)[1]
    missing_from_chroma = min(current_ids)

    # A row that vanished from Chroma (e.g. manual wipe) but whose file is
    # still in the repo, plus an obsolete foreign row still in the store.
    _open_collection(repo.working_dir).delete(ids=[missing_from_chroma])
    _plant_rows(repo.working_dir, 1, ef, "ghost")

    # Legacy per-batch cache marks claiming the opposite of durable truth:
    # "already analyzed" for the row missing from Chroma, and "not yet
    # analyzed" for a row that is really present.
    legacy_cache = Cache("cache", Path(repo.working_dir), dict(engine.cache.data))
    legacy_cache.data.update(
        {
            "chunks_already_analyzed": {missing_from_chroma},
            "chunks_not_yet_analyzed": {regularly_present},
        }
    )
    legacy_cache.persist()
    cache_file = legacy_cache._get_cache_file()

    restarted, _ = _make_engine(repo.working_dir)
    assert "chunks_already_analyzed" not in restarted.cache.data
    assert "chunks_not_yet_analyzed" not in restarted.cache.data

    plan = restarted.plan_indexing()
    # Only the row truly absent from Chroma is pending: the legacy analyzed
    # mark must NOT hide it and the legacy unanalyzed mark must NOT re-plan a
    # chunk that is really present.
    assert [chunk.chunk_id for chunk in plan] == [missing_from_chroma]

    stats = restarted.get_indexing_stats()
    assert stats["pending"] == 1
    assert stats["analyzed"] == stats["total"] - 1
    # The obsolete ghost row is not part of current stats at all.
    assert stats["total"] == len(current_ids)

    bytes_after_plan = cache_file.read_bytes()
    mtime_after_plan = cache_file.stat().st_mtime_ns
    restarted.process_batch(plan)
    # No per-batch pickle write: process_batch leaves the cache file alone.
    assert cache_file.read_bytes() == bytes_after_plan
    assert cache_file.stat().st_mtime_ns == mtime_after_plan
    assert "chunks_already_analyzed" not in restarted.cache.data
    assert "chunks_not_yet_analyzed" not in restarted.cache.data

    # Pruning now removes exactly the obsolete row, keeping every current row.
    assert restarted.pending_prune_count() == 1
    assert restarted.prune_stale() == 1
    assert _collection_ids(repo.working_dir) == current_ids
    assert restarted.pending_prune_count() == 0
    stats = restarted.get_indexing_stats()
    assert stats["pending"] == 0
    assert stats["analyzed"] == stats["total"] == len(current_ids)


# ---------------------------------------------------------------------------
# (2) edit / delete / rename committed files, then plan/index/prune
# ---------------------------------------------------------------------------


def test_replan_after_edit_delete_rename_prunes_only_stale_rows(repo):
    engine, _ef = _make_engine(repo.working_dir)
    _index_all(engine)
    before_ids = _collection_ids(repo.working_dir)
    assert before_ids

    renamed_source = (Path(repo.working_dir) / "file4.js").read_text()
    _commit_change(
        repo, "file4_renamed.js", renamed_source, "rename file4 into a new name"
    )
    repo.add_file_delete_commit("file4.js", "drop the old file4")
    _commit_change(
        repo,
        "file2.py",
        "# edited again\n# fresh new line of content here\nimport math\n",
        "substantially edit file2",
    )
    repo.add_file_delete_commit("file4.md", "drop the markdown file")

    replanned, _ = _make_engine(repo.working_dir)
    pending = replanned.plan_indexing()
    assert pending  # new/edited content needs embedding

    batch_size = replanned.config["server"]["chroma"]["batchSize"]
    for start in range(0, len(pending), batch_size):
        replanned.process_batch(pending[start : start + batch_size])

    assert replanned.get_indexing_stats()["pending"] == 0
    stale_count = replanned.pending_prune_count()
    assert stale_count > 0

    pruned = 0
    while replanned.pending_prune_count():
        pruned += replanned.prune_stale()
    assert pruned == stale_count  # every stale row pruned exactly once

    store_ids = _collection_ids(repo.working_dir)
    # Current rows survive: no row still refers to a removed file, and the
    # store count exactly reconciles old rows, pruned stale rows and new rows.
    assert _current_row_paths(repo.working_dir).isdisjoint({"file4.js", "file4.md"})
    live_paths = _current_row_paths(repo.working_dir)
    assert live_paths <= {
        str(p.relative_to(repo.working_dir))
        for p in Path(repo.working_dir).rglob("*")
        if p.is_file() and ".git" not in str(p)
    }
    assert len(store_ids) + pruned == len(before_ids) + len(pending)
    assert len(store_ids) == replanned.get_indexing_stats()["total"]
    assert store_ids == set(replanned._current_ids)


# ---------------------------------------------------------------------------
# (3) failures and unborn/empty repos never delete
# ---------------------------------------------------------------------------


def test_valid_empty_plan_never_deletes_rows(repo):
    # Unborn repository: no HEAD commit at all, yet Chroma may still hold rows
    # from an earlier incarnation. A valid empty plan must not delete them.
    engine, ef = _make_engine(repo.working_dir)
    _index_all(engine)
    _plant_rows(repo.working_dir, 2, ef, "ghost")
    before = _collection_ids(repo.working_dir)

    subprocess.run(
        ["git", "-C", repo.working_dir, "update-ref", "-d", "HEAD"],
        check=True,
        env={"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
        capture_output=True,
    )

    unborn, _ = _make_engine(repo.working_dir)
    assert unborn.repository.get_status_hash() is not None  # stable unborn hash
    assert unborn.plan_indexing() == []
    assert unborn.pending_prune_count() == 0
    assert unborn.prune_stale() == 0
    # No deletion happened: every stored row (including orphans) survived.
    assert _collection_ids(repo.working_dir) == before


def _sabotage_head_moves_during_materialization(engine):
    original = engine.repository.get_status_hash
    calls = {"count": 0}

    def moving_hash():
        calls["count"] += 1
        return original() if calls["count"] == 1 else original() + "-moved"

    engine.repository.get_status_hash = moving_hash
    return lambda: setattr(engine.repository, "get_status_hash", original)


def _sabotage_git_scan_failure(engine):
    original = engine.repository._get_working_tree_files

    def failing_scan():
        raise RuntimeError("rg exploded mid-scan")

    engine.repository._get_working_tree_files = failing_scan
    return lambda: setattr(engine.repository, "_get_working_tree_files", original)


def _sabotage_chroma_lookup_failure(engine):
    original = engine._query_indexed_ids

    def failing_lookup(ids):
        raise RuntimeError("chroma indexed_ids lookup failed")

    engine._query_indexed_ids = failing_lookup
    return lambda: setattr(engine, "_query_indexed_ids", original)


def _sabotage_chroma_all_ids_failure(engine):
    original = engine._all_indexed_ids

    def failing_enumeration():
        raise RuntimeError("chroma all_ids enumeration failed")

    engine._all_indexed_ids = failing_enumeration
    return lambda: setattr(engine, "_all_indexed_ids", original)


@pytest.mark.parametrize(
    "sabotage",
    [
        _sabotage_head_moves_during_materialization,
        _sabotage_git_scan_failure,
        _sabotage_chroma_lookup_failure,
        _sabotage_chroma_all_ids_failure,
    ],
)
def test_failed_new_plan_revokes_prior_prune_authorization(repo, sabotage):
    engine, ef = _make_engine(repo.working_dir)
    _index_all(engine)
    _plant_rows(repo.working_dir, 1, ef, "ghost")
    ghost_id = "ghost-0"
    assert engine.plan_indexing() == []  # valid plan authorizes ghost prune
    assert engine.pending_prune_count() == 1

    # A failed NEW plan must revoke the previous plan's delete permission.
    restore = sabotage(engine)
    try:
        with pytest.raises(RuntimeError, match="changed|failed|exploded"):
            engine.plan_indexing()
    finally:
        restore()
    assert engine.pending_prune_count() == 0  # prior candidates revoked
    assert engine.prune_stale() == 0  # and cannot be deleted anymore

    # The ghost row was never deleted by any of the failed plans.
    assert ghost_id in _collection_ids(repo.working_dir)
    assert engine.get_indexing_stats()["pending"] == 0


# ---------------------------------------------------------------------------
# (4) multi-page enumeration/deletion beyond 1000 rows
# ---------------------------------------------------------------------------


def test_multi_page_enumeration_and_prune_drains_all_pages(repo):
    from chromadb.api.models.Collection import Collection

    engine, ef = _make_engine(repo.working_dir)
    _index_all(engine)
    current_ids = _collection_ids(repo.working_dir)
    _plant_rows(repo.working_dir, 2500, ef, "paged")
    stale_start = _collection_ids(repo.working_dir) - current_ids
    assert len(stale_start) == 2500

    replanned, _ = _make_engine(repo.working_dir)

    get_calls, delete_calls = [], []
    real_get = Collection.get
    real_delete = Collection.delete

    def spy_get(self, *args, **kwargs):
        if "limit" in kwargs:
            get_calls.append(kwargs["limit"])
        if "ids" in kwargs:
            get_calls.append(len(kwargs["ids"]))
        return real_get(self, *args, **kwargs)

    def spy_delete(self, *args, **kwargs):
        ids = kwargs.get("ids", args[0] if args else [])
        delete_calls.append(list(ids))
        return real_delete(self, *args, **kwargs)

    with (
        patch.object(Collection, "get", spy_get),
        patch.object(Collection, "delete", spy_delete),
    ):
        # Planning enumerates every stored row in bounded API pages, with no
        # skipped rows: all 2500 stale IDs are known even before deletions.
        assert replanned.plan_indexing() == []
        assert replanned.pending_prune_count() == 2500
        assert len(get_calls) >= 2  # full, multi-page enumeration happened
        assert all(0 < page <= 1000 for page in get_calls)

        deleted = 0
        while replanned.pending_prune_count():
            deleted += replanned.prune_stale(1000)
    # Bounded page sizes for every deletion page, nothing skipped or extra.
    assert all(0 < len(page) <= 1000 for page in delete_calls)
    assert deleted == 2500
    assert {
        cid for page in delete_calls for cid in page
    } == stale_start  # no skipped and no extra rows
    assert _collection_ids(repo.working_dir) == current_ids

    # Direct synchronous analyze_codebase drains ALL pages too.
    _plant_rows(repo.working_dir, 2500, ef, "paged2")
    drained, _ = _make_engine(repo.working_dir)
    assert drained.analyze_codebase() == []
    assert drained.pending_prune_count() == 0
    assert _collection_ids(repo.working_dir) == current_ids


# ---------------------------------------------------------------------------
# (5) queued prune tasks interleave with priority-zero query/stats
# ---------------------------------------------------------------------------


def test_queued_prune_tasks_permit_priority_zero_query_and_stats(repo):
    engine, ef = _make_engine(repo.working_dir)
    _index_all(engine)
    _plant_rows(repo.working_dir, 60, ef, "ghost")
    engine.plan_indexing()
    assert engine.pending_prune_count() == 60

    queue, context = _make_task_queue(engine)
    clock = SimpleNamespace(time=lambda: 42.0, monotonic=lambda: 3.0)
    order = []
    original_handler = queue._handle_task

    def recording_handle(context, task, context_error=None):
        order.append(task.name)
        return original_handler(context, task, context_error=context_error)

    queue._handle_task = recording_handle
    with (
        patch.object(task_queue, "time", clock),
        patch.object(TaskQueue, "PRUNE_BATCH_SIZE", 10),
    ):
        queue.handle_maintenance(context)
        assert queue._task_queue.qsize() == 1  # first bounded prune page

        _drive_next(queue, context)  # prune page 1 (10 rows)
        # The prune handler re-enqueues the next page; priority-zero work
        # enqueued now must jump ahead of it.
        assert queue._task_queue.qsize() == 1
        assert queue._task_queue.queue[0].name == "prune_index"
        queue.enqueue("get_stats", wait_for_result=False)
        queue.enqueue(
            "query",
            query="orphan",
            limit_clue=10,
            context_above=0,
            context_below=0,
            priority=HIGH_PRIORITY,
            wait_for_result=False,
        )

        _drive_next(queue, context)  # get_stats before the next prune page
        _drive_next(queue, context)  # query before the next prune page
        assert order == ["prune_index", "get_stats", "query"]

        seen_prunes = 1
        while queue._task_queue.qsize():
            next_name = queue._task_queue.queue[0].name
            _drive_next(queue, context)
            if next_name == "prune_index":
                seen_prunes += 1
        # All six bounded pages (60 rows / PRUNE_BATCH_SIZE 10) ran to the end.
        assert seen_prunes == 6
        assert engine.pending_prune_count() == 0
        assert _collection_ids(repo.working_dir) == set(engine._current_ids)


# ---------------------------------------------------------------------------
# (6) failed deletion keeps candidates, backs off, retries after deadline
# ---------------------------------------------------------------------------


def test_failed_deletion_keeps_candidates_backs_off_and_retries(repo):
    engine, ef = _make_engine(repo.working_dir)
    _index_all(engine)
    _plant_rows(repo.working_dir, 60, ef, "ghost")
    engine.plan_indexing()

    queue, context = _make_task_queue(engine)
    real_delete = engine._delete_indexed_ids
    delete_calls = []

    def flaky_delete(ids):
        delete_calls.append(list(ids))
        if len(delete_calls) == 1:
            raise RuntimeError("chroma delete exploded")
        return real_delete(ids)

    engine._delete_indexed_ids = flaky_delete

    clock = SimpleNamespace(time=lambda: 10.0, monotonic=lambda: 100.0)
    with patch.object(task_queue, "time", clock):
        queue.handle_maintenance(context)
        assert queue._task_queue.qsize() == 1
        _drive_next(queue, context)  # prune fails
        assert len(delete_calls) == 1
        # Failure keeps every candidate, pauses with a monotonic deadline, and
        # does not poison the quarantine or touch Chroma again.
        assert engine.pending_prune_count() == 60
        assert context["paused"] is True
        assert context["pause_reason"] == "storage"
        assert context["retry_after"] == 110.0  # monotonic 100 + 10s backoff
        assert context["replan_pending"] is True
        assert context["failed_chunks"] == set()
        assert queue._task_queue.qsize() == 0

        # Before the deadline nothing happens: no replan, no extra calls.
        clock.time = lambda: 15.0
        clock.monotonic = lambda: 105.0
        queue.handle_maintenance(context)
        assert len(delete_calls) == 1
        assert engine.pending_prune_count() == 60
        assert context["paused"] is True
        assert context["retry_after"] == 110.0

        # After the controlled monotonic deadline, maintenance unpauses and
        # re-enqueues the same prune work against the unchanged HEAD.
        clock.time = lambda: 55.0
        clock.monotonic = lambda: 130.0
        queue.handle_maintenance(context)
        assert context["paused"] is False
        assert queue._task_queue.qsize() == 1
        _drive_next(queue, context)  # retry succeeds
        assert len(delete_calls) == 2
        assert delete_calls[1] == delete_calls[0]  # same candidates retried
        assert engine.pending_prune_count() == 0
        assert _collection_ids(repo.working_dir) == set(engine._current_ids)
        assert context["failed_chunks"] == set()


def test_head_commit_during_chunk_materialization_revokes_pruning(repo):
    engine, embedding = _make_engine(repo.working_dir)
    _index_all(engine)
    _plant_rows(repo.working_dir, 1, embedding)
    assert engine.plan_indexing() == []
    assert engine.pending_prune_count() == 1
    original_chunks = GitFile.get_chunks
    moved = False

    def chunks_while_head_moves(file):
        nonlocal moved
        chunks = original_chunks(file)
        if not moved:
            moved = True
            repo.add_file_change_commit(
                "during-scan.py",
                "print('new revision')\n",
                "commit during chunk discovery",
            )
        return chunks

    with (
        patch.object(GitFile, "get_chunks", chunks_while_head_moves),
        pytest.raises(RuntimeError, match="changed while materializing"),
    ):
        engine.plan_indexing()
    assert moved
    assert engine.pending_prune_count() == 0
    assert engine.prune_stale() == 0
    assert "ghost-0" in _collection_ids(repo.working_dir)
