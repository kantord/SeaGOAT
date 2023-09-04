# pylint: disable=no-member
import copy
import json
import os
import re
import subprocess
from unittest.mock import ANY

import psutil
import pytest
import requests

from seagoat import __version__
from seagoat.server import get_status_data
from seagoat.server import server as seagoat_server
from seagoat.utils.server import get_server_info
from seagoat.utils.server import get_server_info_file_path
from seagoat.utils.wait import wait_for


def normalize_full_paths(data, repo):
    real_repo_path = repo.working_dir
    fake_repo_path = "/path/to/repo"
    deep_copy_of_data = copy.deepcopy(data)

    for result in deep_copy_of_data["results"]:
        result["fullPath"] = result["fullPath"].replace(real_repo_path, fake_repo_path)

    return deep_copy_of_data


def normalize_version(data):
    deep_copy_of_data = copy.deepcopy(data)
    deep_copy_of_data["version"] = "0.0.0-test"

    return deep_copy_of_data


def test_query_codebase(server, snapshot, repo):
    query_text = "Markdown"
    url = f"{server}/query/{query_text}"
    response = requests.get(url)

    assert response.status_code == 200, response.text

    data = response.json()
    normalized_data = normalize_full_paths(data, repo)
    normalized_data = normalize_version(normalized_data)

    assert normalized_data == snapshot
    assert len(data["results"]) > 0
    assert data["version"] == __version__


def test_status_endpoint_with_all_files_analyzed(server, snapshot):
    url = f"{server}/status"
    response = requests.get(url)

    assert response.status_code == 200, response.text

    data = response.json()
    assert data["version"] == __version__
    data = normalize_version(data)

    assert data["stats"]["chunks"]["analyzed"] > 0
    assert data["stats"]["chunks"]["unanalyzed"] == 0
    assert data["stats"]["queue"]["size"] == 0
    assert data == snapshot


@pytest.mark.usefixtures("repo_with_more_files")
def test_status_endpoint_with_some_files_not_analyzed(server):
    url = f"{server}/status"
    response = requests.get(url)

    assert response.status_code == 200, response.text

    data = response.json()
    assert data["version"] == __version__
    data = normalize_version(data)
    assert data["stats"]["chunks"]["analyzed"] > 0
    assert data["stats"]["chunks"]["unanalyzed"] > 0
    assert data["stats"]["queue"]["size"] >= data["stats"]["chunks"]["unanalyzed"]
    assert data["stats"]["accuracy"]["percentage"] == int(
        data["stats"]["accuracy"]["percentage"]
    )
    assert 0 < data["stats"]["accuracy"]["percentage"] < 100


def test_status_1(repo):
    result = subprocess.run(
        ["python", "-m", "seagoat.server", "status", repo.working_dir],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Server is not running" in result.stdout


@pytest.mark.usefixtures("server")
def test_status_2(repo):
    result = subprocess.run(
        ["python", "-m", "seagoat.server", "status", repo.working_dir],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Server is running" in result.stdout


@pytest.mark.usefixtures("server")
def test_stop(repo):
    subprocess.run(
        ["python", "-m", "seagoat.server", "stop", repo.working_dir],
        capture_output=True,
        text=True,
        check=False,
    )
    result = subprocess.run(
        ["python", "-m", "seagoat.server", "status", repo.working_dir],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Server is not running" in result.stdout


def test_status_with_json_when_server_not_running(repo):
    result = subprocess.run(
        ["python", "-m", "seagoat.server", "status", "--json", repo.working_dir],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0

    json_result = json.loads(result.stdout)

    assert json_result.get("isRunning") is False
    assert json_result.get("url") is None


@pytest.mark.usefixtures("server")
def test_status_with_json_when_server_running(repo):
    result = subprocess.run(
        ["python", "-m", "seagoat.server", "status", "--json", repo.working_dir],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0

    json_result = json.loads(result.stdout)

    assert json_result.get("isRunning") is True
    url = json_result.get("url")
    assert re.match(r"http://localhost:\d+", url) is not None


def assert_server_status(repo, running):
    result = subprocess.run(
        ["python", "-m", "seagoat.server", "status", "--json", repo.working_dir],
        capture_output=True,
        text=True,
        check=True,
    )
    json_result = json.loads(result.stdout)
    assert json_result.get("isRunning") == running


def simulate_server_dying(repo):
    try:
        pid = get_status_data(repo.working_dir)["pid"]

        process = psutil.Process(pid)
        process.terminate()
        process.wait(timeout=10)
    except psutil.TimeoutExpired:
        pass


@pytest.mark.usefixtures("server")
def test_server_status_not_running_if_process_does_not_exist(repo):
    assert_server_status(repo, running=True)
    simulate_server_dying(repo)
    assert_server_status(repo, running=False)


@pytest.mark.parametrize("limit_value", [1, 3, 7])
def test_query_with_limit_clue_param(client, limit_value, mock_queue):
    response = client.get(f"/query/Markdown?limitClue={limit_value}")
    mock_queue.enqueue_high_prio.assert_called_with(
        "query",
        query="Markdown",
        limit_clue=limit_value,
        context_below=ANY,
        context_above=ANY,
    )
    assert response.status_code == 200


@pytest.mark.parametrize("context_above", [0, 7])
def test_query_with_context_above(client, context_above, mock_queue):
    response = client.get(f"/query/Markdown?contextAbove={context_above}")
    mock_queue.enqueue_high_prio.assert_called_with(
        "query",
        query="Markdown",
        context_above=context_above,
        limit_clue=ANY,
        context_below=ANY,
    )
    assert response.status_code == 200


@pytest.mark.parametrize("context_below", [0, 2])
def test_query_with_context_below(client, mock_queue, context_below):
    response = client.get(f"/query/Markdown?contextBelow={context_below}")
    mock_queue.enqueue_high_prio.assert_called_with(
        "query",
        query="Markdown",
        context_below=context_below,
        limit_clue=ANY,
        context_above=ANY,
    )
    assert response.status_code == 200


def test_version_option(runner):
    result = runner.invoke(seagoat_server, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"seagoat, version {__version__}"


@pytest.mark.parametrize("custom_port", [7483, 99081])
def test_start_server_on_specific_port(custom_port, repo, mocker, managed_process):
    mocker.patch("seagoat.server.TaskQueue")

    server_cmd = [
        "python",
        "-m",
        "seagoat.server",
        "start",
        "--port",
        str(custom_port),
        repo.working_dir,
    ]

    with managed_process(server_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE):
        wait_for(lambda: os.path.exists(get_server_info_file_path(repo.working_dir)), 8)

        _, _, _, server_address = get_server_info(repo.working_dir)
        assert str(custom_port) in server_address
