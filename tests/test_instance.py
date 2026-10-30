import json
import threading
from pathlib import Path

import psutil
import pytest
import requests

from seagoat.utils.server import (
    Instance,
    claim_start,
    get_free_port,
    instance_answers,
    instance_file_path,
    read_instance,
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
        ("0.0.0.0", "127.0.0.1"),
        ("::", "::1"),
    ],
)
def test_wildcard_host_is_written_as_loopback(host, expected_loopback):
    write_instance(Instance(host=host, port=40123, pid=1234))

    contents = json.loads(instance_file_path().read_text())
    assert contents["host"] == expected_loopback
    assert read_instance() == Instance(host=expected_loopback, port=40123, pid=1234)


def test_claim_start_with_no_instance_calls_bind_once_and_writes_it():
    bound = Instance(host="127.0.0.1", port=40123, pid=1234)
    bind_calls = []

    def bind():
        bind_calls.append(1)
        return bound

    def answers(instance):
        bind_calls.append("answers")
        return False

    result = claim_start(bind, answers=answers)

    assert result is None
    assert bind_calls == [1]
    assert read_instance() == bound


def test_claim_start_with_answering_instance_returns_it_without_calling_bind():
    existing = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(existing)
    bind_calls = []

    def bind():
        bind_calls.append(1)
        return Instance(host="127.0.0.2", port=40124, pid=5678)

    result = claim_start(bind, answers=lambda instance: instance == existing)

    assert result == existing
    assert bind_calls == []
    assert read_instance() == existing


def test_claim_start_with_stale_instance_calls_bind_and_overwrites_file():
    stale = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(stale)
    fresh = Instance(host="127.0.0.2", port=40124, pid=5678)
    bind_calls = []

    def bind():
        bind_calls.append(1)
        return fresh

    result = claim_start(bind, answers=lambda instance: False)

    assert result is None
    assert bind_calls == [1]
    assert read_instance() == fresh


def test_claim_start_concurrent_threads_call_bind_exactly_once():
    bound = Instance(host="127.0.0.1", port=40123, pid=1234)
    bind_calls = []
    results = []
    num_threads = 8
    barrier = threading.Barrier(num_threads)

    def bind():
        bind_calls.append(1)
        return bound

    def answers(instance):
        return instance == bound

    def ask():
        barrier.wait()
        results.append(claim_start(bind, answers=answers))

    threads = [threading.Thread(target=ask) for _ in range(num_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert bind_calls == [1]
    assert results.count(None) == 1
    assert results.count(bound) == num_threads - 1
    assert read_instance() == bound


def test_instance_answers_is_false_for_port_nothing_listens_on():
    port = get_free_port()

    assert instance_answers(Instance(host="127.0.0.1", port=port, pid=1234)) is False


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("127.0.0.1", "http://127.0.0.1:5000/status"),
        ("::1", "http://[::1]:5000/status"),
    ],
)
def test_instance_answers_asks_the_instance_status(mocker, host, url):
    get = mocker.patch.object(
        requests, "get", return_value=mocker.Mock(status_code=200)
    )

    assert instance_answers(Instance(host=host, port=5000, pid=1)) is True
    assert get.call_args.args[0] == url


def test_stop_instance_with_no_file_returns_false():

    instance_file_path().unlink(missing_ok=True)

    assert stop_instance() is False


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

    assert result is True
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

    assert result is True
    process_class.assert_called_once_with(1234)
    fake_process.terminate.assert_not_called()
    assert read_instance() is None
    assert not instance_file_path().exists()


def test_stop_instance_counts_already_gone_process_as_stopped(mocker):

    instance = Instance(host="127.0.0.1", port=40123, pid=1234)
    write_instance(instance)
    mocker.patch(
        "seagoat.utils.server.psutil.Process",
        side_effect=psutil.NoSuchProcess(1234),
    )

    result = stop_instance()

    assert result is True
    assert read_instance() is None
    assert not instance_file_path().exists()
