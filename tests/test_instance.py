import json
import threading
from pathlib import Path

import psutil
import pytest
import requests

from seagoat.utils.server import (
    Instance,
    add_repository,
    claim_start,
    instance_file_path,
    normalize_repo_path,
    read_instance,
    read_repositories,
    repositories_file_path,
    running_instance,
    stop_instance,
    write_instance,
)


@pytest.fixture(autouse=True)
def clean_instance_file():
    path = instance_file_path()
    lock_path = Path(f"{path}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)

    for file_path in (path, lock_path):
        file_path.unlink(missing_ok=True)

    yield

    for file_path in (path, lock_path):
        file_path.unlink(missing_ok=True)


def test_write_then_read_returns_same_instance():
    instance = Instance(host="127.0.0.1", port=40123, pid=1234)

    write_instance(instance)

    assert read_instance() == instance


def test_read_instance_returns_none_when_file_is_missing():
    instance_file_path().unlink(missing_ok=True)

    assert read_instance() is None


def test_read_instance_returns_none_for_invalid_json():
    instance_file_path().write_text("this is not json")

    assert read_instance() is None


@pytest.mark.parametrize(
    ("host", "expected_loopback"),
    [
        ("0.0.0.0", "127.0.0.1"),  # nosec B104 - tests the mapping, no bind
        ("::", "::1"),
    ],
)
def test_wildcard_host_is_written_as_loopback(host, expected_loopback):
    write_instance(Instance(host=host, port=40123, pid=1234))

    contents = json.loads(instance_file_path().read_text())
    assert contents["host"] == expected_loopback
    assert read_instance() == Instance(host=expected_loopback, port=40123, pid=1234)


def test_claim_start_with_no_instance_calls_bind_once_and_writes_it(mocker):
    bound = Instance(host="127.0.0.1", port=40123, pid=1234)
    bind_calls = []

    def bind():
        bind_calls.append(1)
        return bound

    mocker.patch("seagoat.utils.server.running_instance", return_value=None)

    result = claim_start(bind)

    assert result is None
    assert bind_calls == [1]
    assert read_instance() == bound


def test_claim_start_with_running_instance_returns_it_without_calling_bind(mocker):
    existing = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(existing)
    bind_calls = []

    def bind():
        bind_calls.append(1)
        return Instance(host="127.0.0.2", port=40124, pid=5678)

    mocker.patch(
        "seagoat.utils.server.running_instance",
        return_value=(existing, {"pid": existing.pid, "projects": []}),
    )

    result = claim_start(bind)

    assert result == existing
    assert bind_calls == []
    assert read_instance() == existing


def test_claim_start_with_stale_instance_calls_bind_and_overwrites_file(mocker):
    stale = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(stale)
    fresh = Instance(host="127.0.0.2", port=40124, pid=5678)
    bind_calls = []

    def bind():
        bind_calls.append(1)
        return fresh

    mocker.patch("seagoat.utils.server.running_instance", return_value=None)

    result = claim_start(bind)

    assert result is None
    assert bind_calls == [1]
    assert read_instance() == fresh


def test_claim_start_concurrent_threads_call_bind_exactly_once(mocker):
    bound = Instance(host="127.0.0.1", port=40123, pid=1234)
    bind_calls = []
    results = []
    num_threads = 8
    barrier = threading.Barrier(num_threads)

    def bind():
        bind_calls.append(1)
        return bound

    def fake_running_instance():
        instance = read_instance()
        if instance is None:
            return None
        return instance, {"pid": instance.pid, "projects": []}

    mocker.patch(
        "seagoat.utils.server.running_instance", side_effect=fake_running_instance
    )

    def ask():
        barrier.wait()
        results.append(claim_start(bind))

    threads = [threading.Thread(target=ask) for _ in range(num_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert bind_calls == [1]
    assert results.count(None) == 1
    assert results.count(bound) == num_threads - 1
    assert read_instance() == bound


def test_running_instance_is_none_for_port_nothing_listens_on(unused_tcp_port):
    instance = Instance(host="127.0.0.1", port=unused_tcp_port, pid=1234)
    write_instance(instance)

    assert running_instance() is None


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("127.0.0.1", "http://127.0.0.1:5000/status"),
        ("::1", "http://[::1]:5000/status"),
    ],
)
def test_running_instance_asks_the_instance_status(mocker, host, url):
    instance = Instance(host=host, port=5000, pid=1)
    write_instance(instance)
    response = mocker.Mock(status_code=200)
    response.json.return_value = {"pid": 1, "projects": []}
    get = mocker.patch.object(requests, "get", return_value=response)

    assert running_instance() == (instance, {"pid": 1, "projects": []})
    assert get.call_args.args[0] == url


def test_running_instance_is_none_when_answer_comes_from_another_pid(mocker):
    instance = Instance(host="127.0.0.1", port=5000, pid=1234)
    write_instance(instance)
    response = mocker.Mock(status_code=200)
    response.json.return_value = {"pid": 5678, "projects": []}
    mocker.patch.object(requests, "get", return_value=response)

    assert running_instance() is None


def test_running_instance_keeps_the_instance_when_the_file_pid_answers(mocker):
    instance = Instance(host="127.0.0.1", port=5000, pid=1234)
    write_instance(instance)
    response = mocker.Mock(status_code=200)
    response.json.return_value = {"pid": 1234, "projects": ["/path/to/repo"]}
    mocker.patch.object(requests, "get", return_value=response)

    assert running_instance() == (
        instance,
        {"pid": 1234, "projects": ["/path/to/repo"]},
    )


def test_stop_instance_with_no_file_reports_not_running():

    instance_file_path().unlink(missing_ok=True)

    assert stop_instance() == ("not_running", None)


def test_stop_instance_terminates_matching_pid_and_removes_file(mocker):

    instance = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(instance)
    fake_process = mocker.Mock()
    fake_process.is_running.return_value = True
    fake_process.cmdline.return_value = [
        "/path/to/.venv/bin/seagoat-server",
        "start",
        "/path/to/repo",
    ]
    process_class = mocker.patch(
        "seagoat.utils.server.psutil.Process", return_value=fake_process
    )

    result = stop_instance()

    assert result == ("stopped", None)
    process_class.assert_called_once_with(1234)
    fake_process.terminate.assert_called_once()
    assert read_instance() is None
    assert not instance_file_path().exists()


def test_stop_instance_with_unrelated_process_removes_file_and_terminates_nothing(
    mocker,
):

    instance = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(instance)
    fake_process = mocker.Mock()
    fake_process.is_running.return_value = True
    fake_process.cmdline.return_value = ["/usr/bin/python", "other-script.py"]
    process_class = mocker.patch(
        "seagoat.utils.server.psutil.Process", return_value=fake_process
    )

    result = stop_instance()

    assert result == ("not_running", None)
    process_class.assert_called_once_with(1234)
    fake_process.terminate.assert_not_called()
    assert read_instance() is None
    assert not instance_file_path().exists()


def test_stop_instance_removes_file_for_gone_process_and_reports_not_running(mocker):

    instance = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(instance)
    mocker.patch(
        "seagoat.utils.server.psutil.Process",
        side_effect=psutil.NoSuchProcess(1234),
    )

    result = stop_instance()

    assert result == ("not_running", None)
    assert read_instance() is None
    assert not instance_file_path().exists()


def test_stop_instance_removes_file_when_process_is_not_running_anymore(mocker):

    instance = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(instance)
    fake_process = mocker.Mock()
    fake_process.is_running.return_value = False
    mocker.patch("seagoat.utils.server.psutil.Process", return_value=fake_process)

    result = stop_instance()

    assert result == ("not_running", None)
    fake_process.terminate.assert_not_called()
    assert read_instance() is None
    assert not instance_file_path().exists()


def test_stop_instance_keeps_file_and_reports_failure_on_access_denied(mocker):

    instance = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(instance)
    fake_process = mocker.Mock()
    fake_process.cmdline.side_effect = psutil.AccessDenied(1234)
    process_class = mocker.patch(
        "seagoat.utils.server.psutil.Process", return_value=fake_process
    )

    result = stop_instance()

    assert result == ("failed", 1234)
    process_class.assert_called_once_with(1234)
    fake_process.terminate.assert_not_called()
    fake_process.kill.assert_not_called()
    assert read_instance() == instance
    assert instance_file_path().exists()


def test_stop_instance_kills_process_when_terminate_times_out(mocker):

    instance = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(instance)
    fake_process = mocker.Mock()
    fake_process.is_running.return_value = True
    fake_process.cmdline.return_value = [
        "/path/to/.venv/bin/seagoat-server",
        "start",
        "/path/to/repo",
    ]
    mocker.patch("seagoat.utils.server.psutil.Process", return_value=fake_process)
    mocker.patch("seagoat.utils.server._exited", side_effect=[False, True])

    result = stop_instance()

    assert result == ("stopped", None)
    fake_process.terminate.assert_called_once()
    fake_process.kill.assert_called_once()
    assert read_instance() is None
    assert not instance_file_path().exists()


def test_exited_returns_true_for_zombie_process(mocker):
    from seagoat.utils.server import _exited

    fake_process = mocker.Mock()
    fake_process.wait.side_effect = psutil.TimeoutExpired(5)
    fake_process.status.return_value = psutil.STATUS_ZOMBIE

    assert _exited(fake_process, timeout=5) is True
    fake_process.status.assert_called_once_with()


def test_exited_returns_true_when_wait_succeeds(mocker):
    from seagoat.utils.server import _exited

    fake_process = mocker.Mock()

    assert _exited(fake_process, timeout=5) is True
    fake_process.wait.assert_called_once_with(timeout=5)


def test_add_repository_adds_normalized_path(tmp_path):
    repo_path = str(tmp_path / "repo")

    result = add_repository(f"{repo_path}/")

    assert result is True
    assert read_repositories() == [normalize_repo_path(repo_path)]


def test_add_repository_stores_repository_root_for_subdirectory(repo):
    subdirectory = str(Path(repo.working_dir) / "subdirectory")
    Path(subdirectory).mkdir(exist_ok=True)

    result = add_repository(subdirectory)

    assert result is True
    assert read_repositories() == [normalize_repo_path(repo.working_dir)]


def test_add_repository_does_not_add_twice(tmp_path):
    repo_path = str(tmp_path / "repo")

    assert add_repository(repo_path) is True
    assert add_repository(repo_path) is False
    assert add_repository(f"{repo_path}/") is False

    assert read_repositories() == [normalize_repo_path(repo_path)]


def test_add_repository_creates_missing_file(tmp_path):
    repo_path = str(tmp_path / "repo")

    result = add_repository(repo_path)

    assert result is True
    assert repositories_file_path().exists()
    assert read_repositories() == [normalize_repo_path(repo_path)]


def test_add_repository_keeps_existing_repositories(tmp_path):
    repo_path = str(tmp_path / "repo")

    assert add_repository(repo_path) is True
    assert add_repository(f"{tmp_path}/another") is True

    assert read_repositories() == [
        normalize_repo_path(repo_path),
        normalize_repo_path(str(tmp_path / "another")),
    ]


def test_add_repository_does_not_touch_global_config(tmp_path, create_config_file):
    # The list of served repositories lives in repositories.json, not the
    # global config file: add_repository must never rewrite config.yml.
    from seagoat.utils.config import GLOBAL_CONFIG_FILE

    create_config_file(
        {"server": {"readMaxCommits": 6060, "port": 6061}},
        global_config=True,
    )
    global_config_before = GLOBAL_CONFIG_FILE.read_text()
    repo_path = str(tmp_path / "repo")

    result = add_repository(repo_path)

    assert result is True
    assert GLOBAL_CONFIG_FILE.read_text() == global_config_before


def test_read_repositories_returns_empty_list_when_file_is_missing():
    repositories_file_path().unlink(missing_ok=True)

    assert read_repositories() == []


def test_read_repositories_returns_empty_list_for_invalid_json():
    repositories_file_path().write_text("not json", encoding="utf-8")

    assert read_repositories() == []


def test_read_repositories_returns_empty_list_for_non_list():
    from seagoat.utils.json_file import write_to_json_file

    write_to_json_file(repositories_file_path(), {"server": "not a list"})

    assert read_repositories() == []


def test_read_repositories_skips_non_string_entries():
    from seagoat.utils.json_file import write_to_json_file

    write_to_json_file(repositories_file_path(), ["/one", 3, None, "/two"])

    assert read_repositories() == ["/one", "/two"]


def test_write_instance_is_atomic():
    # write_to_json_file writes through a temporary file and os.replace, so a
    # concurrent reader never sees a half-written file.
    import orjson

    from seagoat.utils.json_file import write_to_json_file

    file_path = Path(instance_file_path().parent) / "atomic-test.json"
    file_path.unlink(missing_ok=True)
    try:
        write_to_json_file(file_path, ["a", "b"])

        assert orjson.loads(file_path.read_bytes()) == ["a", "b"]
        assert not list(file_path.parent.glob(".atomic-test.json-*.tmp"))
    finally:
        file_path.unlink(missing_ok=True)
