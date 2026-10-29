from tests.conftest import (
    _delete_unkept_cache_entries,
    _kept_cache_folders,
    keep_cache_folder,
)


def test_cleanup_keeps_registered_folders_and_removes_the_rest(tmp_path):
    kept = tmp_path / "kept"
    kept.mkdir()
    (kept / "data").write_text("x")
    removed = tmp_path / "removed"
    removed.mkdir()
    (tmp_path / "stray-file").write_text("x")
    keep_cache_folder(kept)

    try:
        _delete_unkept_cache_entries(tmp_path)
    finally:
        # Registered folders live for the session; do not leave this temporary one behind
        _kept_cache_folders.discard(kept.resolve())

    assert sorted(path.name for path in tmp_path.iterdir()) == ["kept"]
    assert (kept / "data").exists()
