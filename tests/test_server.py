import copy
import json
import multiprocessing
import subprocess

import pytest
import requests
from appdirs import os
from click.testing import CliRunner

from seagoat.server import get_server_info_file
from seagoat.server import start_server
from seagoat.server import wait_for


@pytest.fixture(name="server")
def _server(repo):
    server_process = multiprocessing.Process(
        target=start_server, args=(repo.working_dir,)
    )
    server_process.start()

    server_info_file = get_server_info_file(repo.working_dir)

    wait_for(lambda: os.path.exists(server_info_file), 120)

    with open(server_info_file, "r", encoding="utf-8") as file:
        server_info = json.load(file)

    yield server_info

    server_process.terminate()
    server_process.join()


@pytest.fixture(name="runner")
def _runner():
    return CliRunner()


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
    host = server["host"]
    port = server["port"]
    query_text = "Markdown"
    url = f"http://{host}:{port}/query/{query_text}"
    response = requests.get(url)

    assert response.status_code == 200, response.text

    data = response.json()
    normalized_data = normalize_full_paths(data, repo)

    assert normalized_data == snapshot
    assert len(data["results"]) > 0


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
