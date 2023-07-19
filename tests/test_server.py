import copy
import json
import re
import subprocess
from importlib.metadata import version

import psutil
import pytest
import requests

from seagoat.server import get_status_data


def normalize_full_paths(data, repo):
    real_repo_path = repo.working_dir
    fake_repo_path = "/path/to/repo"
    deep_copy_of_data = copy.deepcopy(data)

    for result in deep_copy_of_data["results"]:
        result["full_path"] = result["full_path"].replace(
            real_repo_path, fake_repo_path
        )

    return deep_copy_of_data


def test_query_codebase(server, snapshot, repo):
    query_text = "Markdown"
    url = f"{server}/query/{query_text}"
    response = requests.get(url)

    assert response.status_code == 200, response.text

    data = response.json()
    normalized_data = normalize_full_paths(data, repo)
    normalized_data["version"] = "0.0.0-test"

    assert normalized_data == snapshot
    assert len(data["results"]) > 0
    assert data["version"] == version("wheel")


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
    pid = get_status_data(repo.working_dir)["pid"]

    process = psutil.Process(pid)
    process.terminate()
    process.wait(timeout=10)


@pytest.mark.usefixtures("server")
def test_server_status_not_running_if_process_does_not_exist(repo):
    assert_server_status(repo, running=True)
    simulate_server_dying(repo)
    assert_server_status(repo, running=False)
