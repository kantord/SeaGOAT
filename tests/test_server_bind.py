from unittest.mock import patch

import pytest

from seagoat.server import start_server
from seagoat.utils.server import normalize_repo_path


def _fake_claim_start(bind, **kwargs):
    # Pretend we acquired the instance lock and bound successfully, without
    # there being an already-running instance to return.
    bind()


@pytest.fixture(name="mock_serve")
def _mock_serve():
    # create_app would start a worker thread that outlives the test repo
    with (
        patch("seagoat.server.add_repository"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.create_app"),
        patch("seagoat.server.create_server") as mock_create_server,
    ):
        mock_create_server.return_value.effective_port = 40123
        yield mock_create_server


def test_start_server_listens_on_configured_host(repo, create_config_file, mock_serve):
    create_config_file({"server": {"host": "192.0.2.10"}}, global_config=True)

    start_server(repo.working_dir, custom_port=40123)

    mock_serve.assert_called_once()
    assert mock_serve.call_args.kwargs["host"] == "192.0.2.10"
    assert mock_serve.call_args.kwargs["port"] == 40123


def test_start_server_listens_on_localhost_by_default(repo, mock_serve):
    start_server(repo.working_dir, custom_port=40124)

    assert mock_serve.call_args.kwargs["host"] == "127.0.0.1"


def test_under_pytest_instance_lives_in_pytest_directory():
    from seagoat.utils.server import instance_file_path

    assert instance_file_path().parent.name == "seagoat-servers-pytest"


def test_start_server_creates_projects_for_configured_repositories(
    repo, generate_repo, create_config_file
):
    repo1 = generate_repo()
    repo2 = generate_repo()
    create_config_file(
        {"server": {"repositories": [repo1.working_dir, repo2.working_dir]}},
        global_config=True,
    )

    with (
        patch("seagoat.server.TaskQueue"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.create_app") as mock_create_app,
        patch("seagoat.server.create_server") as mock_create_server,
    ):
        mock_create_server.return_value.effective_port = 40125
        start_server(repo.working_dir, custom_port=40125)

    projects = mock_create_app.call_args.args[0]
    paths = projects.repo_paths()
    assert normalize_repo_path(repo.working_dir) in paths
    assert normalize_repo_path(repo1.working_dir) in paths
    assert normalize_repo_path(repo2.working_dir) in paths


def test_start_server_skips_configured_non_git_path(repo, create_config_file, caplog):
    create_config_file(
        {"server": {"repositories": ["/does/not/exist"]}},
        global_config=True,
    )

    with (
        patch("seagoat.server.TaskQueue"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.create_app") as mock_create_app,
        patch("seagoat.server.create_server") as mock_create_server,
    ):
        mock_create_server.return_value.effective_port = 40126
        start_server(repo.working_dir, custom_port=40126)

    projects = mock_create_app.call_args.args[0]
    assert "/does/not/exist" not in projects.repo_paths()
    assert normalize_repo_path(repo.working_dir) in projects.repo_paths()
    assert "Skipping configured repository" in caplog.text
