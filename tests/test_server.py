import copy
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from unittest.mock import ANY

import psutil
import pytest
import requests

from seagoat import __version__
from seagoat.engine import Engine
from seagoat.projects import Projects
from seagoat.queue.task_queue import TaskQueue
from seagoat.server import ExitCode, create_app, get_status_data
from seagoat.server import server as seagoat_server
from seagoat.utils.config import GLOBAL_CONFIG_FILE
from seagoat.utils.server import (
    Instance,
    instance_url,
    normalize_repo_path,
    read_instance,
    read_repositories,
    running_instance,
)
from seagoat.utils.wait import wait_for
from tests.fixtures.config import NOT_A_NUMBER, write_invalid_config
from tests.fixtures.git import make_git_repo


def _server_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "seagoat.server", *args]


def server_cli(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run one `seagoat-server` command to completion."""
    return subprocess.run(
        _server_command(*args),
        capture_output=True,
        text=True,
        check=check,
        timeout=30,
    )


@pytest.fixture
def start_seagoat_server(managed_process):
    """Start `seagoat-server start ARGS` as a child process and wait for it."""

    @contextmanager
    def _start(*args: str):
        with managed_process(
            _server_command("start", *args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as process:
            wait_for(lambda: running_instance() is not None, 8)
            instance = read_instance()
            assert instance is not None
            yield process, instance

    return _start


def stop_seagoat_server(server_process: subprocess.Popen) -> None:
    result = server_cli("stop")
    assert result.returncode == 0, result.stderr
    # The test started the server, so it reaps it
    server_process.wait(timeout=10)


def served_projects(instance: Instance) -> list[str]:
    response = requests.get(f"{instance_url(instance)}/status")
    assert response.status_code == 200
    return response.json()["projects"]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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
    url = f"{server}/lines/query"
    response = requests.post(
        url, json={"query_text": "Markdown", "repoPath": repo.working_dir}
    )

    assert response.status_code == 200, response.text

    data = response.json()
    normalized_data = normalize_full_paths(data, repo)
    normalized_data = normalize_version(normalized_data)

    assert normalized_data == snapshot
    assert len(data["results"]) > 0
    assert data["version"] == __version__


def test_status_endpoint_with_all_files_analyzed(server, snapshot, repo):
    url = f"{server}/status"

    def fully_analyzed():
        stats = requests.post(url, json={"repoPath": repo.working_dir}).json()["stats"]
        # Before indexing starts nothing is unanalyzed yet either, so also
        # require that something was analyzed
        chunks = stats["chunks"]
        return (
            chunks["analyzed"] > 0
            and chunks["unanalyzed"] == 0
            and stats["queue"]["size"] == 0
        )

    # Each status request is a task for the single worker, and indexing only
    # starts once the worker has been idle for 0.1s, so poll slower than that
    wait_for(fully_analyzed, timeout=10, period=0.5)
    response = requests.post(url, json={"repoPath": repo.working_dir})

    assert response.status_code == 200, response.text

    data = response.json()
    assert data["version"] == __version__
    data = normalize_version(data)

    assert data["stats"]["chunks"]["analyzed"] > 0
    assert data["stats"]["chunks"]["unanalyzed"] == 0
    assert data["stats"]["queue"]["size"] == 0
    assert data == snapshot


@pytest.mark.usefixtures("repo_with_more_files")
def test_status_endpoint_with_some_files_not_analyzed(repo):
    class NoMaintenanceTaskQueue(TaskQueue):
        def handle_maintenance(self, context):
            # Indexing happens only during maintenance; the test controls it
            pass

    # Analyze one chunk synchronously and nothing more, so the repository is
    # partially analyzed however fast the machine is.
    Engine(repo.working_dir).analyze_codebase(minimum_chunks_to_analyze=1)
    projects = Projects(
        lambda path, config: NoMaintenanceTaskQueue(
            repo_path=path, minimum_chunks_to_analyze=0
        )
    )
    queue = projects.get(repo.working_dir).queue

    app = create_app(projects, "127.0.0.1")
    response = app.test_client().post("/status", json={"repoPath": repo.working_dir})
    queue.shutdown()

    assert response.status_code == 200, response.text
    data = response.get_json()
    assert data["version"] == __version__
    data = normalize_version(data)
    assert data["stats"]["chunks"]["unanalyzed"] > 0
    assert data["stats"]["accuracy"]["percentage"] == int(
        data["stats"]["accuracy"]["percentage"]
    )
    assert 0 < data["stats"]["accuracy"]["percentage"] < 100


def test_status_reports_no_instance_when_none_runs(repo, runner):
    result = server_cli("status")
    assert result.returncode == 0
    assert "No SeaGOAT instance running" in result.stdout

    result = runner.invoke(seagoat_server, ["server-info"])
    servers_data = json.loads(result.output)
    current_repo = normalize_repo_path(repo.working_dir)
    assert current_repo not in servers_data["servers"]


@pytest.mark.usefixtures("server")
def test_status_reports_running_instance(repo):
    result = server_cli("status")
    assert result.returncode == 0
    assert "Instance is running" in result.stdout


def test_stop(repo, start_seagoat_server):
    with start_seagoat_server(repo.working_dir) as (server_process, instance):
        assert psutil.pid_exists(instance.pid)

        stop_seagoat_server(server_process)

        status_result = server_cli("status")
        assert status_result.returncode == 0
        assert "No SeaGOAT instance running" in status_result.stdout


def test_stop_accepts_and_ignores_a_path(repo, start_seagoat_server):
    with start_seagoat_server(repo.working_dir) as (server_process, instance):
        assert psutil.pid_exists(instance.pid)

        stop_result = server_cli("stop", "/some/repo")
        assert stop_result.returncode == 0, stop_result.stderr
        assert "Instance stopped." in stop_result.stdout
        # This test is the server's parent, so it reaps it
        server_process.wait(timeout=10)

        status_result = server_cli("status")
        assert status_result.returncode == 0
        assert "No SeaGOAT instance running" in status_result.stdout


@pytest.mark.timeout(120)
def test_one_instance_serves_two_repositories(generate_repo, start_seagoat_server):
    repo_a = generate_repo()
    repo_b = generate_repo()
    repo_b.add_file_change_commit(
        file_name="only_in_b.md",
        contents="zanzibar_marker_only_in_repo_b\n",
        commit_message="add a file only repo B has",
    )

    with start_seagoat_server(repo_a.working_dir) as (server_process, instance):
        assert psutil.pid_exists(instance.pid)

        add_repo_b_result = server_cli("start", repo_b.working_dir)
        assert add_repo_b_result.returncode == 0, add_repo_b_result.stderr

        instance = read_instance()
        assert instance is not None
        # Still the same instance: the file records the same pid as before
        assert instance.pid == server_process.pid

        assert normalize_repo_path(repo_a.working_dir) in served_projects(instance)
        assert normalize_repo_path(repo_b.working_dir) in served_projects(instance)

        project_status_response = requests.post(
            f"{instance_url(instance)}/status",
            json={"repoPath": repo_b.working_dir},
        )
        assert project_status_response.status_code == 200

        # Each query goes to the project its repoPath names
        def query(repo):
            response = requests.post(
                f"{instance_url(instance)}/lines/query",
                json={
                    "queryText": "zanzibar_marker_only_in_repo_b",
                    "repoPath": repo.working_dir,
                },
            )
            assert response.status_code == 200, response.text
            return [result["path"] for result in response.json()["results"]]

        wait_for(lambda: "only_in_b.md" in query(repo_b), 30)
        assert "only_in_b.md" not in query(repo_a)

        stop_seagoat_server(server_process)


@pytest.mark.timeout(120)
def test_bad_configured_repository_does_not_take_instance_down(
    generate_repo, create_repositories_file, start_seagoat_server
):
    good_repo = generate_repo()
    bad_repo = generate_repo()
    write_invalid_config(bad_repo.working_dir)
    create_repositories_file([bad_repo.working_dir, good_repo.working_dir])
    requested_repo = generate_repo()

    with start_seagoat_server(requested_repo.working_dir) as (server_process, instance):
        assert psutil.pid_exists(instance.pid)

        projects = served_projects(instance)
        assert normalize_repo_path(requested_repo.working_dir) in projects
        assert normalize_repo_path(good_repo.working_dir) in projects
        assert normalize_repo_path(bad_repo.working_dir) not in projects

        # A reload triggered by a later `start` must not take the instance down
        reload_response = requests.post(f"{instance_url(instance)}/reload")
        assert reload_response.status_code == 200
        assert reload_response.json()["projects"] == projects

        status_response = requests.get(f"{instance_url(instance)}/status")
        assert status_response.status_code == 200

        stop_seagoat_server(server_process)


@pytest.mark.timeout(120)
def test_start_reports_error_when_running_instance_cannot_serve_requested_repo(
    generate_repo, start_seagoat_server
):
    good_repo = generate_repo()
    bad_repo = generate_repo()
    write_invalid_config(bad_repo.working_dir)

    with start_seagoat_server(good_repo.working_dir) as (server_process, instance):
        start_bad_result = server_cli("start", bad_repo.working_dir)
        assert start_bad_result.returncode == ExitCode.SERVER_ERROR, (
            start_bad_result.stdout,
            start_bad_result.stderr,
        )
        assert "Could not load" in start_bad_result.stderr
        assert "Repository added to the running instance" not in start_bad_result.stdout

        # The running instance still serves the repository it could load
        assert normalize_repo_path(good_repo.working_dir) in served_projects(instance)

        stop_seagoat_server(server_process)


def test_start_fails_loudly_when_requested_repo_cannot_load(generate_repo):
    bad_repo = generate_repo()
    write_invalid_config(bad_repo.working_dir)

    result = server_cli("start", bad_repo.working_dir)
    assert result.returncode != 0
    assert read_instance() is None


def test_status_with_json_when_server_not_running(repo):
    result = server_cli("status", "--json")
    assert result.returncode == 0

    json_result = json.loads(result.stdout)

    assert json_result.get("isRunning") is False
    assert json_result.get("url") is None


@pytest.mark.usefixtures("server")
def test_status_with_json_when_server_running(repo):
    result = server_cli("status", "--json")
    assert result.returncode == 0

    json_result = json.loads(result.stdout)

    assert json_result.get("isRunning") is True
    url = json_result.get("url")
    assert re.match(r"http://127\.0\.0\.1:\d+", url) is not None


@pytest.mark.usefixtures("server")
def test_status_with_repo_path_tells_whether_the_instance_serves_it(repo, tmp_path):
    def is_running(repo_path):
        result = server_cli("status", repo_path, "--json", check=True)
        return json.loads(result.stdout)["isRunning"]

    subdirectory = os.path.join(repo.working_dir, "subdirectory")
    os.makedirs(subdirectory, exist_ok=True)

    assert is_running(repo.working_dir) is True
    assert is_running(subdirectory) is True
    assert is_running(str(tmp_path)) is False


def assert_server_status(running):
    result = server_cli("status", "--json", check=True)
    json_result = json.loads(result.stdout)
    assert json_result.get("isRunning") == running


def simulate_server_dying(repo):
    try:
        pid = get_status_data()["pid"]

        process = psutil.Process(pid)
        process.terminate()
        process.wait(timeout=10)
    except psutil.TimeoutExpired:
        pass


@pytest.mark.usefixtures("server")
def test_server_status_not_running_if_process_does_not_exist(repo, runner):
    current_repo = normalize_repo_path(repo.working_dir)

    assert_server_status(running=True)

    result1 = runner.invoke(seagoat_server, ["server-info"])
    servers_data1 = json.loads(result1.output)
    assert servers_data1["servers"][current_repo]["isRunning"]

    simulate_server_dying(repo)

    assert_server_status(running=False)

    result2 = runner.invoke(seagoat_server, ["server-info"])
    servers_data2 = json.loads(result2.output)
    assert current_repo not in servers_data2["servers"]


@pytest.mark.parametrize("limit_value", [1, 3, 7])
def test_query_with_limit_clue_param(client, limit_value, mock_queue, repo):
    response = client.post(
        "lines/query",
        json={
            "queryText": "Markdown",
            "limitClue": limit_value,
            "repoPath": repo.working_dir,
        },
    )
    mock_queue.enqueue.assert_called_with(
        "query",
        query="Markdown",
        limit_clue=limit_value,
        context_below=ANY,
        context_above=ANY,
    )
    assert response.status_code == 200


@pytest.mark.parametrize("context_above", [0, 7])
def test_query_with_context_above(client, context_above, mock_queue, repo):
    response = client.post(
        "lines/query",
        json={
            "queryText": "Markdown",
            "contextAbove": context_above,
            "repoPath": repo.working_dir,
        },
    )
    mock_queue.enqueue.assert_called_with(
        "query",
        query="Markdown",
        context_above=context_above,
        limit_clue=ANY,
        context_below=ANY,
    )
    assert response.status_code == 200


@pytest.mark.parametrize("context_below", [0, 2])
def test_query_with_context_below(client, mock_queue, context_below, repo):
    response = client.post(
        "lines/query",
        json={
            "queryText": "Markdown",
            "contextBelow": context_below,
            "repoPath": repo.working_dir,
        },
    )
    mock_queue.enqueue.assert_called_with(
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


def test_start_server_on_specific_port(repo, start_seagoat_server):
    custom_port = free_port()

    with start_seagoat_server("--port", str(custom_port), repo.working_dir) as (
        _,
        instance,
    ):
        server_address = instance_url(instance)
        assert str(custom_port) in server_address


def test_query_codebase_no_results(server, snapshot, repo):
    query_text = "a_string_we_are_sure_does_not_exist_in_any_file_12345"
    url = f"{server}/lines/query"
    response = requests.post(
        url, json={"queryText": query_text, "repoPath": repo.working_dir}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert not data["results"]
    assert normalize_version(data) == snapshot


@pytest.mark.usefixtures("server")
def test_servers_info_includes_version_and_server_details(runner, repo):
    result = runner.invoke(seagoat_server, ["server-info"])

    assert result.exit_code == 0

    servers_data = json.loads(result.output)
    assert servers_data["version"] == __version__
    assert "servers" in servers_data
    assert servers_data["globalConfigFile"] == str(GLOBAL_CONFIG_FILE)

    for repo_path, server in servers_data["servers"].items():
        assert "host" in server
        assert "port" in server
        assert "address" in server
        assert server["address"].startswith("http://")
        assert str(server["port"]) in server["address"]
        assert server["host"] in server["address"]
        assert server["isRunning"] in {False, True}
        assert server["repoPath"] == repo_path
        assert os.path.isdir(server["cacheLocation"]["chroma"])
        parent_folder_of_repo_cache = os.path.dirname(server["cacheLocation"]["chroma"])
        assert parent_folder_of_repo_cache == servers_data["globalCache"]

    assert len(servers_data["servers"]) >= 1
    current_repo = normalize_repo_path(repo.working_dir)
    assert current_repo in servers_data["servers"]
    assert servers_data["servers"][current_repo]["isRunning"]


def test_start_server_on_custom_port_using_config_files(
    repo, start_seagoat_server, create_config_file
):
    custom_port = free_port()
    create_config_file(
        {
            "server": {
                "port": custom_port,
            }
        },
        global_config=True,
    )

    with start_seagoat_server(repo.working_dir) as (_, instance):
        server_address = instance_url(instance)
        assert str(custom_port) in server_address


def test_query_files_endpoint(server, snapshot, repo):
    url = f"{server}/files/query"
    response = requests.post(
        url, json={"query_text": "Markdown", "repoPath": repo.working_dir}
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert len(data["results"]) > 0
    assert data["version"] == __version__
    assert normalize_full_paths(data, repo)["results"] == snapshot


def test_server_shows_error_when_folder_is_not_a_git_repo(runner_with_error):
    with tempfile.TemporaryDirectory() as new_directory:
        result = runner_with_error.invoke(seagoat_server, ["start", new_directory])

    assert result.exit_code == ExitCode.NOT_A_GIT_REPO


@pytest.mark.timeout(120)
def test_start_on_directory_serves_each_git_repository_inside_it(
    tmp_path, start_seagoat_server
):
    parent = tmp_path / "projects"
    repo_a = make_git_repo(parent / "a")
    repo_b = make_git_repo(parent / "b")

    with start_seagoat_server(str(parent)) as (server_process, instance):
        projects = served_projects(instance)
        assert normalize_repo_path(str(repo_a)) in projects
        assert normalize_repo_path(str(repo_b)) in projects

        # Both repositories are also recorded in the repositories file
        repositories = read_repositories()
        assert normalize_repo_path(str(repo_a)) in repositories
        assert normalize_repo_path(str(repo_b)) in repositories

        # A repository created later is not picked up until start is rerun
        repo_c = make_git_repo(parent / "c")
        assert normalize_repo_path(str(repo_c)) not in served_projects(instance)

        # Running start again on the same directory serves the new repository
        add_c_result = server_cli("start", str(parent))
        assert add_c_result.returncode == 0, add_c_result.stderr
        assert "Added repositories to the running instance" in add_c_result.stdout
        assert normalize_repo_path(str(repo_c)) in add_c_result.stdout

        assert normalize_repo_path(str(repo_c)) in served_projects(instance)

        stop_result = server_cli("stop")
        assert stop_result.returncode == 0, stop_result.stderr
        # The start output names every repository it added
        stdout, _stderr = server_process.communicate()
        stdout = stdout.decode()
        assert normalize_repo_path(str(repo_a)) in stdout
        assert normalize_repo_path(str(repo_b)) in stdout


@pytest.mark.timeout(120)
def test_start_on_directory_does_not_search_deeper_than_direct_children(
    tmp_path, start_seagoat_server
):
    parent = tmp_path / "projects"
    repo_direct = make_git_repo(parent / "direct")
    deep_repo = make_git_repo(parent / "nested" / "deep")
    (parent / "plain").mkdir()

    with start_seagoat_server(str(parent)) as (server_process, instance):
        projects = served_projects(instance)
        assert normalize_repo_path(str(repo_direct)) in projects
        assert normalize_repo_path(str(deep_repo)) not in projects
        assert normalize_repo_path(str(parent / "nested")) not in projects

        repositories = read_repositories()
        assert normalize_repo_path(str(repo_direct)) in repositories
        assert normalize_repo_path(str(deep_repo)) not in repositories

        stop_result = server_cli("stop")
        assert stop_result.returncode == 0, stop_result.stderr
        assert server_process.wait(timeout=10) is not None


def test_start_on_directory_without_git_repositories_fails(tmp_path, runner_with_error):
    parent = tmp_path / "projects"
    parent.mkdir()
    (parent / "plain").mkdir()

    result = runner_with_error.invoke(seagoat_server, ["start", str(parent)])

    assert result.exit_code == ExitCode.NOT_A_GIT_REPO
    combined = (result.stdout or "") + (result.stderr or "")
    assert "SeaGOAT can only operate in Git repositories" in combined


@pytest.mark.timeout(120)
def test_start_on_directory_where_no_repository_loads_fails(
    tmp_path, runner_with_error
):
    parent = tmp_path / "projects"
    bad_repos = [make_git_repo(parent / name) for name in ("bad1", "bad2")]
    for bad_repo in bad_repos:
        write_invalid_config(bad_repo, NOT_A_NUMBER)

    result = runner_with_error.invoke(seagoat_server, ["start", str(parent)])

    # One bad repository in a folder only warns (test_server_bind.py); when
    # nothing in the folder loads, the start fails and no instance starts.
    assert result.exit_code == ExitCode.SERVER_ERROR
    combined = (result.stdout or "") + (result.stderr or "")
    assert "Could not load" in combined
    assert read_instance() is None
