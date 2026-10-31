from unittest.mock import MagicMock, patch

import pytest
import requests

from seagoat.projects import Projects
from seagoat.server import ExitCode, start_server
from seagoat.utils.server import Instance, normalize_repo_path
from tests.fixtures.config import NOT_A_NUMBER, write_invalid_config
from tests.fixtures.git import make_git_repo


def _fake_claim_start(bind, prepare=None, **kwargs):
    # Pretend we acquired the instance lock and bound successfully, without
    # there being an already-running instance to return.
    if prepare is not None:
        prepare()
    bind()


def projects_start_server_would_serve(repo_path: str) -> Projects:
    """Run start_server without binding a port or starting workers.

    Returns the projects it hands to the app.
    """
    with (
        patch("seagoat.server.TaskQueue"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.create_app") as mock_create_app,
        patch("seagoat.server.create_server") as mock_create_server,
    ):
        mock_create_server.return_value.effective_port = 40125
        start_server(repo_path, custom_port=40125)

    return mock_create_app.call_args.args[0]


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

    projects = projects_start_server_would_serve(repo.working_dir)
    paths = projects.repo_paths()
    assert normalize_repo_path(repo.working_dir) in paths
    assert normalize_repo_path(repo1.working_dir) in paths
    assert normalize_repo_path(repo2.working_dir) in paths


def test_start_server_skips_configured_repository_with_invalid_config(
    repo, generate_repo, create_repositories_file, caplog
):
    good_repo = generate_repo()
    bad_repo = generate_repo()
    write_invalid_config(bad_repo.working_dir)
    create_repositories_file([bad_repo.working_dir, good_repo.working_dir])

    projects = projects_start_server_would_serve(repo.working_dir)
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
    write_invalid_config(bad_repo.working_dir, NOT_A_NUMBER)
    create_repositories_file([normalize_repo_path(bad_repo.working_dir)])

    with (
        patch("seagoat.server.add_repository"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.create_app") as mock_create_app,
        patch("seagoat.server.create_server") as mock_create_server,
        pytest.raises(SystemExit) as excinfo,
    ):
        start_server(bad_repo.working_dir, custom_port=40128)

    assert excinfo.value.code == ExitCode.SERVER_ERROR
    assert "Could not load" in capsys.readouterr().err
    # The port was bound first, and the bound socket is closed again when the
    # explicitly started repository fails to load.
    mock_create_app.assert_called_once()
    mock_create_server.return_value.close.assert_called_once()


def test_start_server_binds_the_port_before_loading_any_project(
    repo, generate_repo, create_repositories_file, capsys
):
    """A port already in use exits with BIND_FAILED before any project loads."""
    other_repo = generate_repo()
    create_repositories_file([repo.working_dir, other_repo.working_dir])

    with (
        patch("seagoat.server.add_repository"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.load_configured_projects") as mock_load,
        patch("seagoat.server.create_app"),
        patch(
            "seagoat.server.create_server",
            side_effect=OSError(98, "Address already in use"),
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        start_server(repo.working_dir, custom_port=40198)

    assert excinfo.value.code == ExitCode.BIND_FAILED
    assert "could not bind" in capsys.readouterr().err
    assert mock_load.call_count == 0


def test_start_server_still_loads_listed_repositories_after_binding(
    repo, generate_repo, create_repositories_file
):
    """The app and the projects object are created before loading, so the
    server that is already bound serves every listed repository."""
    repo1 = generate_repo()
    create_repositories_file([repo.working_dir, repo1.working_dir])

    projects = projects_start_server_would_serve(repo.working_dir)
    assert normalize_repo_path(repo.working_dir) in projects.repo_paths()
    assert normalize_repo_path(repo1.working_dir) in projects.repo_paths()


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

    projects = projects_start_server_would_serve(repo.working_dir)
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
            "seagoat.server.running_instance",
            return_value=(instance, {"pid": instance.pid, "projects": status_projects}),
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


def test_folder_of_repositories_inside_a_work_tree_serves_its_children(tmp_path):
    from seagoat.server import find_repositories_to_serve

    make_git_repo(tmp_path)  # say, a dotfiles repository at ~
    make_git_repo(tmp_path / "repos" / "a")
    make_git_repo(tmp_path / "repos" / "b")

    repositories, found_in_directory = find_repositories_to_serve(
        str(tmp_path / "repos")
    )

    assert found_in_directory
    assert [normalize_repo_path(path) for path in repositories] == [
        normalize_repo_path(tmp_path / "repos" / "a"),
        normalize_repo_path(tmp_path / "repos" / "b"),
    ]


def test_plain_subdirectory_of_a_repository_serves_the_repository(tmp_path):
    from seagoat.server import find_repositories_to_serve

    make_git_repo(tmp_path)
    (tmp_path / "src").mkdir()

    assert find_repositories_to_serve(str(tmp_path / "src")) == (
        [str(tmp_path / "src")],
        False,
    )


def test_one_bad_repository_in_a_folder_does_not_block_the_others(tmp_path, capsys):
    make_git_repo(tmp_path / "good")
    make_git_repo(tmp_path / "bad")
    write_invalid_config(tmp_path / "bad", NOT_A_NUMBER)

    with (
        patch("seagoat.server.TaskQueue"),
        patch("seagoat.server.claim_start", side_effect=_fake_claim_start),
        patch("seagoat.server.create_app") as mock_create_app,
        patch("seagoat.server.create_server") as mock_create_server,
    ):
        mock_create_server.return_value.effective_port = 40124
        start_server(str(tmp_path))

    captured = capsys.readouterr()
    bad, good = (normalize_repo_path(tmp_path / name) for name in ("bad", "good"))
    assert f"Warning: could not load {bad}" in captured.err
    assert good in captured.out
    assert bad not in captured.out
    assert mock_create_app.call_args.args[0].repo_paths() == [good]
    mock_create_server.return_value.run.assert_called_once()
