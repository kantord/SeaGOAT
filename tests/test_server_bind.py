from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from seagoat.server import ExitCode, start_server
from seagoat.utils.server import Instance, normalize_repo_path


def _fake_claim_start(bind, prepare=None, **kwargs):
    # Pretend we acquired the instance lock and bound successfully, without
    # there being an already-running instance to return.
    if prepare is not None:
        prepare()
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
    repo, generate_repo, create_repositories_file
):
    repo1 = generate_repo()
    repo2 = generate_repo()
    create_repositories_file([repo1.working_dir, repo2.working_dir])

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


def test_start_server_skips_configured_repository_with_invalid_config(
    repo, generate_repo, create_repositories_file, caplog
):
    good_repo = generate_repo()
    bad_repo = generate_repo()
    (Path(bad_repo.working_dir) / ".seagoat.yml").write_text(
        "server:\n  repositories: this-is-not-a-list\n",
        encoding="utf-8",
    )
    create_repositories_file([bad_repo.working_dir, good_repo.working_dir])

    with (
        patch("seagoat.server.TaskQueue"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.create_app") as mock_create_app,
        patch("seagoat.server.create_server") as mock_create_server,
    ):
        mock_create_server.return_value.effective_port = 40127
        start_server(repo.working_dir, custom_port=40127)

    projects = mock_create_app.call_args.args[0]
    paths = projects.repo_paths()
    assert normalize_repo_path(bad_repo.working_dir) not in paths
    assert normalize_repo_path(good_repo.working_dir) in paths
    assert normalize_repo_path(repo.working_dir) in paths
    assert "Skipping configured repository" in caplog.text
    assert bad_repo.working_dir in caplog.text


def test_start_server_fails_loudly_when_requested_repo_cannot_load(
    generate_repo, create_repositories_file, capsys
):
    bad_repo = generate_repo()
    (Path(bad_repo.working_dir) / ".seagoat.yml").write_text(
        "server:\n  readMaxCommits: not-a-number\n",
        encoding="utf-8",
    )
    create_repositories_file([normalize_repo_path(bad_repo.working_dir)])

    with (
        patch("seagoat.server.add_repository"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.create_app") as mock_create_app,
        patch("seagoat.server.create_server"),
        pytest.raises(SystemExit) as excinfo,
    ):
        start_server(bad_repo.working_dir, custom_port=40128)

    assert excinfo.value.code == ExitCode.SERVER_ERROR
    assert "Could not load" in capsys.readouterr().err
    mock_create_app.assert_not_called()


def test_start_server_reports_repositories_file_write_failure(repo, capsys):
    from seagoat.utils.server import repositories_file_path

    def _failing_add_repository(repo_path):
        raise OSError("disk full")

    def _claim_start_running_prepare(bind, prepare=None, **kwargs):
        if prepare is not None:
            prepare()
        return Instance(host="127.0.0.1", port=45678, pid=1234)

    with (
        patch("seagoat.server.add_repository", side_effect=_failing_add_repository),
        patch("seagoat.server.claim_start", side_effect=_claim_start_running_prepare),
        patch("seagoat.server.create_app"),
        patch("seagoat.server.create_server"),
        pytest.raises(SystemExit) as excinfo,
    ):
        start_server(repo.working_dir, custom_port=40140)

    assert excinfo.value.code == ExitCode.SERVER_ERROR
    captured = capsys.readouterr()
    assert "could not write" in captured.err
    assert str(repositories_file_path()) in captured.err
    assert "disk full" in captured.err


def test_start_server_skips_configured_non_git_path(
    repo, create_repositories_file, caplog
):
    create_repositories_file(["/does/not/exist"])

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


def test_start_server_fails_loudly_when_reload_of_running_instance_fails(repo, capsys):

    def _fake_claim_start(bind, **kwargs):
        return Instance(host="127.0.0.1", port=45678, pid=1234)

    def _failing_reload(*args, **kwargs):
        response = MagicMock()
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "500 Server Error"
        )
        return response

    with (
        patch("seagoat.server.add_repository"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.requests.post", side_effect=_failing_reload),
        pytest.raises(SystemExit) as excinfo,
    ):
        start_server(repo.working_dir, custom_port=40129)

    assert excinfo.value.code == ExitCode.SERVER_ERROR
    captured = capsys.readouterr()
    assert "could not reload the running instance" in captured.err
    assert "Repository added to the running instance" not in captured.out


def test_start_server_fails_loudly_when_reload_connection_fails(repo, capsys):

    def _fake_claim_start(bind, **kwargs):
        return Instance(host="127.0.0.1", port=45678, pid=1234)

    with (
        patch("seagoat.server.add_repository"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch(
            "seagoat.server.requests.post",
            side_effect=requests.exceptions.ConnectionError("connection refused"),
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        start_server(repo.working_dir, custom_port=40130)

    assert excinfo.value.code == ExitCode.SERVER_ERROR
    captured = capsys.readouterr()
    assert "could not reload the running instance" in captured.err
    assert "Repository added to the running instance" not in captured.out


def test_start_server_fails_loudly_when_running_instance_cannot_serve_requested_repo(
    repo, capsys
):
    def _fake_claim_start(bind, **kwargs):
        return Instance(host="127.0.0.1", port=45678, pid=1234)

    def _reload_without_requested_repo(*args, **kwargs):
        response = MagicMock()
        response.json.return_value = {"projects": []}
        return response

    with (
        patch("seagoat.server.add_repository"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch(
            "seagoat.server.requests.post", side_effect=_reload_without_requested_repo
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        start_server(repo.working_dir, custom_port=40131)

    assert excinfo.value.code == ExitCode.SERVER_ERROR
    captured = capsys.readouterr()
    assert "Could not load" in captured.err
    assert repo.working_dir in captured.err
    assert "Repository added to the running instance" not in captured.out


def test_start_server_reports_success_when_running_instance_serves_requested_repo(
    repo, capsys
):
    def _fake_claim_start(bind, **kwargs):
        return Instance(host="127.0.0.1", port=45678, pid=1234)

    def _reload_with_requested_repo(*args, **kwargs):
        response = MagicMock()
        response.json.return_value = {
            "projects": [normalize_repo_path(repo.working_dir)]
        }
        return response

    with (
        patch("seagoat.server.add_repository"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.requests.post", side_effect=_reload_with_requested_repo),
    ):
        start_server(repo.working_dir, custom_port=40132)

    captured = capsys.readouterr()
    assert "Repository added to the running instance" in captured.out


def _running_instance_reloading(reload_answer, status_projects):
    instance = Instance(host="127.0.0.1", port=45678, pid=1234)
    response = MagicMock()
    response.json.return_value = reload_answer
    return (
        patch("seagoat.server.claim_start", return_value=instance),
        patch(
            "seagoat.server.fetch_status", return_value={"projects": status_projects}
        ),
        patch("seagoat.server.requests.post", return_value=response),
    )


def test_start_server_names_the_load_error_of_the_running_instance(repo, capsys):
    root = normalize_repo_path(repo.working_dir)
    claim, status, post = _running_instance_reloading(
        {"projects": [], "failed": {root: "bad batchSize"}}, []
    )
    with (
        patch("seagoat.server.add_repository"),
        claim,
        status,
        post,
        pytest.raises(SystemExit) as excinfo,
    ):
        start_server(repo.working_dir)

    assert excinfo.value.code == ExitCode.SERVER_ERROR
    assert f"Could not load {root}: bad batchSize" in capsys.readouterr().err


def test_start_server_says_when_repo_is_already_served(repo, capsys):
    root = normalize_repo_path(repo.working_dir)
    claim, status, post = _running_instance_reloading(
        {"projects": [root], "failed": {}}, [root]
    )
    with patch("seagoat.server.add_repository"), claim, status, post:
        start_server(repo.working_dir, custom_port=1111)

    captured = capsys.readouterr()
    assert f"{root} is already served by the instance" in captured.out
    assert "keeps port 45678" in captured.err
