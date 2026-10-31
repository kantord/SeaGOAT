import yaml

from tests.conftest import (
    BASELINE_GLOBAL_CONFIG,
    SESSION_TEMP_DIR,
    _clean_instance_state,
    _delete_unkept_cache_entries,
    _kept_cache_folders,
    keep_cache_folder,
)


def _read_global_config():
    from seagoat.utils.config import GLOBAL_CONFIG_FILE

    with open(GLOBAL_CONFIG_FILE, encoding="utf-8") as file:
        return yaml.safe_load(file)


def _assert_baseline_global_config():
    assert _read_global_config() == BASELINE_GLOBAL_CONFIG


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


def test_session_uses_its_own_cache_and_config_directories():
    from seagoat.utils.config import GLOBAL_CONFIG_FILE
    from seagoat.utils.server import (
        instance_file_path,
        repositories_file_path,
    )

    assert instance_file_path().is_relative_to(SESSION_TEMP_DIR)
    assert repositories_file_path().is_relative_to(SESSION_TEMP_DIR)
    assert GLOBAL_CONFIG_FILE.is_relative_to(SESSION_TEMP_DIR)


def test_clean_instance_state_removes_instance_and_repositories_and_writes_baseline_config():
    from seagoat.utils.config import GLOBAL_CONFIG_FILE
    from seagoat.utils.server import (
        instance_file_path,
        repositories_file_path,
    )

    instance_path = instance_file_path()
    repositories_path = repositories_file_path()
    for path in (instance_path, repositories_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path == instance_path else "[]")
    GLOBAL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_CONFIG_FILE.write_text("server: {}\n")

    _clean_instance_state()

    assert not instance_path.exists()
    assert not repositories_path.exists()
    assert GLOBAL_CONFIG_FILE.exists()
    _assert_baseline_global_config()


def test_state_is_cleaned_after_each_test_plant_files():
    # Plant state that would poison a later test; the autouse cleanup runs
    # after this test and again before the next one.
    from seagoat.utils.config import GLOBAL_CONFIG_FILE
    from seagoat.utils.server import (
        instance_file_path,
        repositories_file_path,
    )

    instance_path = instance_file_path()
    repositories_path = repositories_file_path()
    for path in (instance_path, repositories_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path == instance_path else "[]")
    GLOBAL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_CONFIG_FILE.write_text("server: {}\n")


def test_state_is_cleaned_before_each_test_no_leftovers():
    from seagoat.utils.config import GLOBAL_CONFIG_FILE
    from seagoat.utils.server import (
        instance_file_path,
        repositories_file_path,
    )

    assert not instance_file_path().exists()
    assert not repositories_file_path().exists()
    assert GLOBAL_CONFIG_FILE.exists()
    _assert_baseline_global_config()
