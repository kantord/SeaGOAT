import copy
import json
import multiprocessing
import subprocess
import time

import pytest
import requests
from click.testing import CliRunner

from seagoat.server import get_server_info_file
from seagoat.server import start_server


@pytest.fixture(name="server")
def _server(repo):
    server_process = multiprocessing.Process(
        target=start_server, args=(repo.working_dir,)
    )
    server_process.start()
    time.sleep(0.5)

    server_info_file = get_server_info_file(repo.working_dir)
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

    assert response.status_code == 200

    data = response.json()
    normalized_data = normalize_full_paths(data, repo)

    assert normalized_data == snapshot
    assert len(data["results"]) > 0


def test_status_command_sequence(repo):
    def start_seagoat_server():
        server_command = ["python", "-m", "seagoat.server", "start", repo.working_dir]
        # This is explicitly closed later on
        # pylint: disable=consider-using-with
        subprocess.Popen(server_command)
        time.sleep(1)

    def run_server_command(command: str):
        return subprocess.run(
            ["python", "-m", "seagoat.server", command, repo.working_dir],
            capture_output=True,
            text=True,
            check=False,
        )

    result = run_server_command("status")
    assert result.returncode == 0
    assert "Server is not running." in result.stdout

    start_seagoat_server()
    result = run_server_command("status")
    assert result.returncode == 0
    assert "Server is running." in result.stdout

    run_server_command("stop")
    result = run_server_command("status")
    assert result.returncode == 0
    assert "Server is not running." in result.stdout
