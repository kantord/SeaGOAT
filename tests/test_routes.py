import os
from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from seagoat import __version__
from seagoat.projects import Projects, git_root
from seagoat.server import create_app
from seagoat.utils.server import normalize_repo_path

REMOTE_ADDR = "192.0.2.7"


@pytest.fixture(name="create_client")
def _create_client():
    def _create(resolve=None):
        queues = {}

        def queue_factory(path, config):
            queue = MagicMock()
            queue.enqueue.return_value = b'{"results": []}'
            queues[path] = queue
            return queue

        projects = Projects(queue_factory, resolve=resolve or git_root)
        app = create_app(projects, "127.0.0.1")
        app.config["TESTING"] = True
        client = app.test_client()
        client._queues = queues  # type: ignore
        client._projects = projects  # type: ignore
        return client

    return _create


def test_two_projects_route_to_their_own_queues(create_client, generate_repo):
    repo1 = generate_repo()
    repo2 = generate_repo()
    client = create_client()
    client._projects.get(repo1.working_dir)
    client._projects.get(repo2.working_dir)

    response1 = client.post(
        "/lines/query",
        json={"repoPath": repo1.working_dir, "queryText": "one"},
    )
    response2 = client.post(
        "/lines/query",
        json={"repoPath": repo2.working_dir, "queryText": "two"},
    )

    queue1 = client._queues[normalize_repo_path(repo1.working_dir)]
    queue2 = client._queues[normalize_repo_path(repo2.working_dir)]
    assert response1.status_code == 200
    assert response2.status_code == 200
    assert queue1 is not queue2
    queue1.enqueue.assert_called_once_with(
        "query", query="one", limit_clue=ANY, context_above=ANY, context_below=ANY
    )
    queue2.enqueue.assert_called_once_with(
        "query", query="two", limit_clue=ANY, context_above=ANY, context_below=ANY
    )


def test_loopback_caller_gets_404_for_unknown_project(create_client, generate_repo):
    repo = generate_repo()
    resolve_calls = []

    def recording_resolve(path):
        resolve_calls.append(path)
        return git_root(path)

    client = create_client(resolve=recording_resolve)
    assert client._projects.repo_paths() == []

    response = client.post(
        "/lines/query",
        json={"repoPath": repo.working_dir, "queryText": "hello"},
    )

    data = response.get_json()
    assert response.status_code == 404
    assert data["code"] == 404
    assert data["error"]["type"] == "UnknownProject"
    assert repo.working_dir in data["error"]["message"]
    assert f"seagoat-server start {repo.working_dir}" in data["error"]["message"]
    assert client._projects.repo_paths() == []
    assert resolve_calls == []


def test_remote_caller_gets_answer_from_loaded_project(create_client, generate_repo):
    repo = generate_repo()
    client = create_client()
    client._projects.get(repo.working_dir)
    queue = client._queues[normalize_repo_path(repo.working_dir)]

    response = client.post(
        "/lines/query",
        json={"repoPath": repo.working_dir, "queryText": "hello"},
        environ_base={"REMOTE_ADDR": REMOTE_ADDR},
    )

    assert response.status_code == 200
    assert response.data == b'{"results": []}'
    queue.enqueue.assert_called_once()


def test_remote_caller_cannot_create_project(create_client, generate_repo):
    repo = generate_repo()
    resolve_calls = []

    def recording_resolve(path):
        resolve_calls.append(path)
        return git_root(path)

    client = create_client(resolve=recording_resolve)

    response = client.post(
        "/lines/query",
        json={"repoPath": repo.working_dir},
        environ_base={"REMOTE_ADDR": REMOTE_ADDR},
    )

    data = response.get_json()
    assert response.status_code == 404
    assert data["code"] == 404
    assert data["error"]["type"] == "UnknownProject"
    assert repo.working_dir in data["error"]["message"]
    assert f"seagoat-server start {repo.working_dir}" in data["error"]["message"]
    assert client._projects.repo_paths() == []
    assert resolve_calls == []


def test_no_repo_path_with_one_loaded_project(create_client, generate_repo):
    repo = generate_repo()
    client = create_client()
    client._projects.get(repo.working_dir)
    queue = client._queues[normalize_repo_path(repo.working_dir)]

    response = client.post("/lines/query", json={})

    assert response.status_code == 200
    queue.enqueue.assert_called_once()


def test_no_repo_path_with_two_loaded_projects(create_client, generate_repo):
    repo1 = generate_repo()
    repo2 = generate_repo()
    client = create_client()
    client._projects.get(repo1.working_dir)
    client._projects.get(repo2.working_dir)

    response = client.post("/lines/query", json={})

    data = response.get_json()
    assert response.status_code == 400
    assert data["code"] == 400
    assert data["error"]["type"] == "RepoPathRequired"
    assert data["error"]["message"] == "repoPath required (2 projects loaded)"


def test_no_repo_path_with_no_projects(create_client):
    client = create_client()

    response = client.post("/lines/query", json={})

    data = response.get_json()
    assert response.status_code == 400
    assert data["code"] == 400
    assert data["error"]["type"] == "RepoPathRequired"
    assert data["error"]["message"] == "repoPath required (0 projects loaded)"


def test_loopback_non_git_repo_path_gets_404(create_client, tmp_path):
    client = create_client()

    response = client.post("/lines/query", json={"repoPath": str(tmp_path)})

    data = response.get_json()
    assert response.status_code == 404
    assert data["code"] == 404
    assert data["error"]["type"] == "UnknownProject"
    assert str(tmp_path) in data["error"]["message"]
    assert f"seagoat-server start {tmp_path}" in data["error"]["message"]


def test_status_returns_loaded_projects_stats(create_client, generate_repo):
    repo = generate_repo()
    client = create_client()
    client._projects.get(repo.working_dir)
    queue = client._queues[normalize_repo_path(repo.working_dir)]
    queue.enqueue.return_value = {"status": "ok"}

    response = client.post("/status", json={"repoPath": repo.working_dir})

    assert response.status_code == 200
    queue.enqueue.assert_called_once_with("get_stats")
    data = response.get_json()
    assert data["stats"] == {"status": "ok"}


def test_status_describes_instance_without_touching_project_queues(
    create_client, generate_repo
):
    repo1 = generate_repo()
    repo2 = generate_repo()
    client = create_client()
    client._projects.get(repo1.working_dir)
    client._projects.get(repo2.working_dir)

    response = client.get("/status")

    assert response.status_code == 200
    data = response.get_json()
    assert data["version"] == __version__
    assert data["pid"] == os.getpid()
    assert data["projects"] == [
        normalize_repo_path(repo1.working_dir),
        normalize_repo_path(repo2.working_dir),
    ]
    for queue in client._queues.values():
        queue.enqueue.assert_not_called()


def test_reload_loads_newly_listed_repository(
    create_client, generate_repo, create_config_file
):
    repo1 = generate_repo()
    repo2 = generate_repo()
    create_config_file(
        {"server": {"repositories": [repo1.working_dir]}},
        global_config=True,
    )
    client = create_client()

    response = client.post("/reload")

    assert response.status_code == 200
    assert response.get_json() == {"projects": [normalize_repo_path(repo1.working_dir)]}

    create_config_file(
        {"server": {"repositories": [repo1.working_dir, repo2.working_dir]}},
        global_config=True,
    )

    response = client.post("/reload")

    assert response.status_code == 200
    assert response.get_json()["projects"] == [
        normalize_repo_path(repo1.working_dir),
        normalize_repo_path(repo2.working_dir),
    ]


def test_reload_skips_configured_repository_with_invalid_config(
    create_client, generate_repo, create_config_file, caplog
):
    repo = generate_repo()
    bad_repo = generate_repo()
    (Path(bad_repo.working_dir) / ".seagoat.yml").write_text(
        "server:\n  repositories: this-is-not-a-list\n",
        encoding="utf-8",
    )
    create_config_file(
        {"server": {"repositories": [repo.working_dir, bad_repo.working_dir]}},
        global_config=True,
    )
    client = create_client()

    response = client.post("/reload")

    assert response.status_code == 200
    assert response.get_json()["projects"] == [normalize_repo_path(repo.working_dir)]
    assert "Skipping configured repository" in caplog.text
    assert bad_repo.working_dir in caplog.text


def test_reload_skips_paths_that_are_not_repositories(
    create_client, generate_repo, create_config_file, tmp_path, caplog
):
    repo = generate_repo()
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    create_config_file(
        {"server": {"repositories": [repo.working_dir, str(not_a_repo)]}},
        global_config=True,
    )
    client = create_client()

    response = client.post("/reload")

    assert response.status_code == 200
    assert response.get_json()["projects"] == [normalize_repo_path(repo.working_dir)]
    assert "Skipping configured repository" in caplog.text
