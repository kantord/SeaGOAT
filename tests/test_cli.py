import os
import re
import shutil
import tempfile

import orjson
import pytest
import requests
from click.testing import CliRunner

from seagoat import __version__
from seagoat.cli import ExitCode, query_server, seagoat, warn_if_update_available
from seagoat.utils.cli_display import is_bat_installed
from seagoat.utils.server import Instance


@pytest.fixture
def assume_bat_not_installed():
    """Some tests here check is_bat_installed itself, so do not replace it."""


def status_payload(accuracy: int = 100) -> dict:
    """A /status response for a fully indexed repository by default."""
    return {
        "stats": {
            "chunks": {"analyzed": 100, "unanalyzed": 0},
            "queue": {"size": 0},
            "accuracy": {"percentage": accuracy},
        },
        "version": __version__,
    }


def mock_running_instance(mocker) -> None:
    mocker.patch(
        "seagoat.cli.running_instance",
        return_value=(Instance(host="localhost", port=1234, pid=1), {"pid": 1}),
    )


def test_non_git_path_fails_early_with_git_repository_error(
    tmp_path, runner_with_error
):
    non_git_dir = tmp_path / "plain"
    non_git_dir.mkdir()

    result = runner_with_error.invoke(
        seagoat, ["some query", str(non_git_dir), "--no-color"]
    )

    assert result.exit_code == ExitCode.NOT_A_GIT_REPO
    assert (
        f"{non_git_dir} is not inside a Git repository" in result.output + result.stderr
    )
    assert "seagoat-server start" not in result.output + result.stderr


@pytest.mark.usefixtures("mock_accuracy_warning")
def test_forwards_repository_root_when_run_from_subdirectory(
    mock_server_factory, mocker, runner, repo
):
    mock_server_factory([], manually_mock_request=True)
    request_args = {}

    def fake_requests(*args, **kwargs):
        mock_response = mocker.Mock()
        mock_response.text = '{"results": []}'
        request_args["json"] = kwargs.get("json", {})
        return mock_response

    mocker.patch("seagoat.cli.requests.post", side_effect=fake_requests)
    subdirectory = os.path.join(repo.working_dir, "subdirectory")
    os.makedirs(subdirectory, exist_ok=True)

    result = runner.invoke(seagoat, ["JavaScript", subdirectory, "--no-color"])

    assert result.exit_code == 0
    assert request_args["json"]["repoPath"] == os.path.abspath(repo.working_dir)


@pytest.fixture(name="get_request_args_from_cli_call")
def get_request_args_from_cli_call_(mock_server_factory, mocker, runner, repo):
    def _run_cli(cli_args: list[str]):
        mock_server_factory(
            [
                ["hello.txt", ["foo", "bar", "baz"]],
                ["foobar.py", ["def hello():", "    print('world')"]],
                ["foobar2.py", ["def hola():", "    print('mundo')"]],
                ["foobar3.py", ["def bonjour():", "    print('monde')"]],
                ["foobar.fake", ["fn hello()", "    echo('world')"]],
                ["foobar2.fake", ["fn hola()", "    echo('mundo')"]],
                ["foobar3.fake", ["fn bonjour()", "    echo('monde')"]],
            ],
            manually_mock_request=True,
        )

        request_args = {}

        def fake_requests(*args, **kwargs):
            mock_response = mocker.Mock()
            mock_response.text = '{"results": []}'

            request_args["url"] = args[0]
            request_args["json"] = kwargs.get("json", {})

            return mock_response

        mocked_requests_post = mocker.patch(
            "seagoat.cli.requests.post", side_effect=fake_requests
        )
        query = "JavaScript"
        result = runner.invoke(
            seagoat,
            [query, repo.working_dir, "--no-color", *cli_args],
        )
        assert result.exit_code == 0
        mocked_requests_post.assert_called_once()

        return request_args

    return _run_cli


@pytest.fixture(name="mock_response")
def mock_response_(mocker):
    def _mock_response(json_data, status_code=200):
        mock_resp = mocker.Mock(spec=requests.Response)
        mock_resp.status_code = status_code
        mock_resp.text = orjson.dumps(json_data)
        return mock_resp

    return _mock_response


@pytest.fixture
def mock_accuracy_warning(mocker):
    def _noop(*args, **kwargs):
        pass

    mocker.patch("seagoat.cli.display_accuracy_warning", _noop)


@pytest.fixture
def mock_query_server(mocker):
    def _mocked_query_server(*args, **kwargs):
        return []

    mocker.patch("seagoat.cli.query_server", _mocked_query_server)


@pytest.mark.usefixtures("mock_query_server")
@pytest.mark.parametrize("accuracy_percentage", [50, 75, 99, 100])
def test_seagoat_warns_on_incomplete_accuracy(
    accuracy_percentage,
    runner_with_error,
    mocker,
    mock_response,
):
    mock_status_response = status_payload(accuracy=accuracy_percentage)

    mocked_status_request = mocker.patch(
        "requests.post", return_value=mock_response(mock_status_response)
    )
    mock_running_instance(mocker)

    query = "some random query"
    result = runner_with_error.invoke(seagoat, [query, ".", "--no-color"])

    if accuracy_percentage < 100:
        assert (
            "Warning: SeaGOAT is still analyzing your repository. "
            + f"The results displayed have an estimated accuracy of {accuracy_percentage}%"
            in result.stderr
        )
    else:
        assert "Warning" not in result.stderr

    assert mocked_status_request.call_args.args[0] == "http://localhost:1234/status"
    assert mocked_status_request.call_args.kwargs["json"] == {
        "repoPath": os.path.abspath(".")
    }


@pytest.mark.usefixtures("mock_accuracy_warning")
def test_forwards_repo_path_to_server(get_request_args_from_cli_call, repo):
    request_args = get_request_args_from_cli_call([])
    assert request_args["json"]["repoPath"] == os.path.abspath(repo.working_dir)


@pytest.mark.usefixtures("mock_accuracy_warning")
@pytest.mark.parametrize("max_length", [1, 2, 10])
def test_forwards_limit_clue_to_server(max_length, get_request_args_from_cli_call):
    request_args = get_request_args_from_cli_call(["--max-results", str(max_length)])
    assert request_args["json"]["limitClue"] == max_length


@pytest.mark.usefixtures("server", "mock_accuracy_warning")
def test_integration_test_without_color(snapshot, repo, mocker, runner, temporary_cd):
    mocker.patch("os.isatty", return_value=True)
    query = "JavaScript"
    with temporary_cd(repo.working_dir):
        result = runner.invoke(seagoat, [query, ".", "--no-color"])

    assert str(result.output) == snapshot
    assert result.exit_code == 0


@pytest.mark.usefixtures("server", "mock_accuracy_warning")
def test_integration_test_vimgrep_mode(snapshot, repo, mocker, runner, temporary_cd):
    mocker.patch("os.isatty", return_value=True)
    query = "JavaScript"
    with temporary_cd(repo.working_dir):
        result = runner.invoke(seagoat, [query, ".", "--vimgrep"])

    assert str(result.output) == snapshot
    assert result.exit_code == 0


@pytest.mark.usefixtures("mock_accuracy_warning")
@pytest.mark.parametrize(
    "max_length, command_option, expected_length",
    [
        (20, "-l", 20),
        (0, "-l", 3),
        (1, "--max-results", 3),
        (3, "--max-results", 3),
        (4, "--max-results", 5),
        (6, "-l", 7),
        (2, "-l", 3),
    ],
)
def test_limit_output_length(
    repo,
    max_length,
    command_option,
    mock_server_factory,
    runner,
    expected_length,
):
    mock_server_factory(
        [
            ["hello.txt", ["foo", "bar", "baz"]],
            ["foobar.py", ["def hello():", "    print('world')"]],
            ["foobar2.py", ["def hola():", "    print('mundo')"]],
            ["foobar3.py", ["def bonjour():", "    print('monde')"]],
            ["foobar.fake", ["fn hello()", "    echo('world')"]],
            ["foobar2.fake", ["fn hola()", "    echo('mundo')"]],
            ["foobar3.fake", ["fn bonjour()", "    echo('monde')"]],
        ]
    )
    query = "JavaScript"
    result = runner.invoke(
        seagoat,
        [
            query,
            repo.working_dir,
            "--no-color",
            command_option,
            str(max_length),
        ],
    )

    assert len(result.output.splitlines()) == min(expected_length, 15)
    assert result.output.splitlines() == result.output.splitlines()[:expected_length]
    assert result.exit_code == 0


def test_version_option(runner):
    result = runner.invoke(seagoat, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"seagoat, version {__version__}"


def test_server_is_not_running_error(mocker, repo, snapshot, mock_spinner):
    mock_running_instance(mocker)
    runner = CliRunner()

    mocker.patch("os.isatty", return_value=True)
    query = "JavaScript"
    result = runner.invoke(seagoat, [query, repo.working_dir])

    assert result.exit_code == ExitCode.SERVER_NOT_RUNNING
    assert "The SeaGOAT server is not running." in result.output
    assert f"seagoat-server start {repo.working_dir}" in result.output


def test_documentation_present(runner):
    result = runner.invoke(seagoat, ["--help"])
    assert result.exit_code == 0
    assert "Query your codebase for your QUERY" in result.output


@pytest.mark.usefixtures("mock_accuracy_warning")
@pytest.mark.parametrize("context_above", [1, 2, 10])
def test_forwards_context_above_to_server(
    context_above, get_request_args_from_cli_call
):
    request_args1 = get_request_args_from_cli_call(
        ["--context-above", str(context_above)]
    )
    assert request_args1["json"]["contextAbove"] == context_above

    request_args2 = get_request_args_from_cli_call([f"-B{context_above}"])
    assert request_args2["json"]["contextAbove"] == context_above


@pytest.mark.usefixtures("mock_accuracy_warning")
@pytest.mark.parametrize("context_below", [1, 2, 10])
def test_forwards_context_below_to_server(
    context_below, get_request_args_from_cli_call
):
    request_args1 = get_request_args_from_cli_call(
        ["--context-below", str(context_below)]
    )
    assert request_args1["json"]["contextBelow"] == context_below

    request_args2 = get_request_args_from_cli_call([f"-A{context_below}"])
    assert request_args2["json"]["contextBelow"] == context_below


@pytest.mark.usefixtures("mock_accuracy_warning")
@pytest.mark.parametrize("context", [0, 1, 2, 10])
def test_forwards_context_to_server(context, get_request_args_from_cli_call):
    request_args1 = get_request_args_from_cli_call(["--context", str(context)])
    assert request_args1["json"]["contextAbove"] == context
    assert request_args1["json"]["contextBelow"] == context

    request_args2 = get_request_args_from_cli_call([f"-C{context}"])
    assert request_args2["json"]["contextAbove"] == context
    assert request_args2["json"]["contextBelow"] == context


@pytest.mark.usefixtures("mock_accuracy_warning")
def test_limit_does_not_apply_to_context_lines(repo, mock_server_factory, runner):
    mock_server_factory(
        [
            ["hello.txt", ["foo", "a context line", "baz"]],
            ["foobar.py", ["def hello():", "    print('world')"]],
            [
                "foobar2.py",
                [
                    "def hola():",
                    "    print('mundo') # I am a context line",
                    "# screaming: context!",
                ],
            ],
            ["foobar3.py", ["def bonjour():", "    print('monde')"]],
            [
                "foobar.fake",
                [
                    "fn hello()",
                    "    echo('world') // I am also a context line",
                ],
            ],
            ["foobar2.fake", ["fn hola()", "    echo('mundo')"]],
            [
                "foobar3.fake",
                [
                    "fn bonjour()",
                    "    echo('monde') /* I am too a context line */",
                ],
            ],
        ]
    )
    query = "JavaScript"
    result = runner.invoke(
        seagoat,
        [query, repo.working_dir, "--no-color", "-l5", "--context=3"],
    )

    assert len(result.output.splitlines()) > 5
    assert result.exit_code == 0


@pytest.mark.usefixtures("mock_accuracy_warning")
def test_context_lines_at_the_end_are_included(repo, mock_server_factory, runner):
    mock_server_factory(
        [
            [
                "hello.py",
                [
                    "foo()",
                    "# a context line",
                    "baz()",
                    "# another context line",
                    "# 3rd context line",
                ],
            ],
        ]
    )
    query = "JavaScript"
    result = runner.invoke(
        seagoat,
        [query, repo.working_dir, "--no-color", "-l2", "--context=3"],
    )

    assert len(result.output.splitlines()) == 5
    assert result.exit_code == 0


@pytest.mark.usefixtures("mock_accuracy_warning")
def test_context_lines_are_not_included_from_other_files_when_limit_exceeded(
    repo, mock_server_factory, runner
):
    mock_server_factory(
        [
            [
                "hello.py",
                [
                    "foo()",
                    "# a context line",
                    "baz()",
                    "# another context line",
                    "# 3rd context line",
                ],
            ],
            [
                "hello2.py",
                [
                    "# a context line",
                    "baz()",
                    "# another context line",
                    "# 3rd context line",
                ],
            ],
        ]
    )
    query = "JavaScript"
    result = runner.invoke(
        seagoat,
        [query, repo.working_dir, "--no-color", "-l2", "--context=3"],
    )

    assert len(result.output.splitlines()) == 5
    assert result.exit_code == 0


@pytest.mark.usefixtures("mock_accuracy_warning")
@pytest.mark.parametrize("args", [(), ("--reverse",)], ids=["default", "reversed"])
def test_reverse_ordering(
    repo, mock_server_factory, runner, snapshot, args: tuple[str, ...]
):
    mock_server_factory(
        [
            ["hello.txt", ["foo", "a context line", "baz"]],
            ["foobar.py", ["def hello():", "    print('world')"]],
        ]
    )
    query = "JavaScript"
    result = runner.invoke(
        seagoat,
        [query, repo.working_dir, "--no-color", *args],
    )

    assert str(result.output) == snapshot
    assert result.exit_code == 0


@pytest.mark.parametrize(
    "error_message, error_code",
    [("File Not Found on Server", 500), ("Database Connection Failed", 503)],
)
def test_server_error_handling(
    repo,
    mock_server_error_factory,
    runner_with_error,
    error_message,
    error_code,
):
    mock_server_error_factory(error_message, error_code)

    query = "JavaScript"
    result = runner_with_error.invoke(
        seagoat,
        [query, repo.working_dir, "--no-color", "-l2", "--context=3"],
    )

    assert result.exit_code == ExitCode.SERVER_ERROR
    assert error_message in result.stderr


def test_bat_installed(mocker):
    mock_run = mocker.patch("seagoat.utils.cli_display.subprocess.run")
    mock_run.return_value.returncode = 0
    assert is_bat_installed() is True


def test_bat_not_installed_when_command_is_missing(mocker):
    mocker.patch(
        "seagoat.utils.cli_display.subprocess.run",
        side_effect=FileNotFoundError,
    )
    assert is_bat_installed() is False


def test_bat_not_installed_when_command_fails(mocker):
    mock_run = mocker.patch("seagoat.utils.cli_display.subprocess.run")
    mock_run.return_value.returncode = 1
    assert is_bat_installed() is False


@pytest.mark.parametrize("newer_version", ["4243.3424.2", "99992.0.0"])
def test_warn_if_update_available_shows_warning(
    mocker, capsys, mock_response, newer_version
):
    mock_version_response = {"info": {"version": newer_version}}

    mocker.patch("requests.get", return_value=mock_response(mock_version_response))

    warn_if_update_available()
    captured = capsys.readouterr()

    assert (
        f"Warning: An updated version {newer_version} of SeaGOAT is available. You have {__version__}."
        in captured.err
    )


@pytest.mark.parametrize(
    # 0.54.17 is older than 1.x even though "0.54.17" != __version__
    "older_or_same_version",
    [__version__, "0.54.17", "0.1.0"],
)
def test_warn_if_update_available_no_warning(
    mocker, capsys, mock_response, older_or_same_version
):
    mock_version_response = {"info": {"version": older_or_same_version}}

    mocker.patch("requests.get", return_value=mock_response(mock_version_response))

    warn_if_update_available()
    captured = capsys.readouterr()

    assert "Warning" not in captured.err


@pytest.mark.usefixtures(
    "server",
    "mock_accuracy_warning",
    "bat_available",
)
def test_integration_test_no_results(snapshot, repo, mocker, runner):
    mocker.patch("os.isatty", return_value=True)
    mocker.patch("seagoat.utils.cli_display.display_blocks_with_bat", return_value=True)
    query = "a_string_we_are_sure_does_not_exist_in_any_file_12345"
    result = runner.invoke(seagoat, [query, repo.working_dir])
    assert str(result.output) == snapshot
    assert result.exit_code == 0


@pytest.mark.usefixtures("mock_accuracy_warning")
@pytest.mark.parametrize(
    "remote_host",
    ["http://example.com/potato", "https://ejemplo.es/nose/seagoat"],
)
def test_configure_remote_server_address(
    remote_host, get_request_args_from_cli_call, create_config_file
):
    create_config_file({"client": {"host": remote_host}}, global_config=True)
    request_args = get_request_args_from_cli_call([])
    assert request_args["url"].startswith(remote_host)
    assert "repoPath" not in request_args["json"]


@pytest.mark.usefixtures("mock_query_server")
def test_status_request_with_remote_server_sends_no_repo_path(
    runner_with_error, mocker, mock_response, create_config_file
):
    create_config_file(
        {"client": {"host": "http://example.com/nose"}}, global_config=True
    )
    mock_status_response = status_payload()

    mocked_status_request = mocker.patch(
        "requests.post", return_value=mock_response(mock_status_response)
    )

    result = runner_with_error.invoke(seagoat, ["some random query", ".", "--no-color"])

    assert result.exit_code == 0
    assert mocked_status_request.call_args.args[0] == "http://example.com/nose/status"
    assert "repoPath" not in mocked_status_request.call_args.kwargs["json"]


@pytest.mark.usefixtures("mock_accuracy_warning", "bat_available")
def test_connecting_to_remote_server(
    repo,
    mocker,
    runner,
    temporary_cd,
    server,
    create_config_file,
    bat_calls,
    snapshot,
):
    """
    When the user requests data from a remote server,
    the display logic should not rely on full path
    as the full path might be different on the remote server
    than locally

    Also the same files might not always exist.

    This test also tests that results are correctly displayed with bat
    """

    create_config_file({"client": {"host": server}}, global_config=True)
    mocker.patch("os.isatty", return_value=True)
    query = "JavaScript"

    def query_server_side_effect(*args, **kwargs):
        results = query_server(*args, **kwargs)

        results = [{**result, "fullPath": "/non/existent/path/"} for result in results]

        return results

    mocker.patch("seagoat.cli.query_server", side_effect=query_server_side_effect)

    with tempfile.TemporaryDirectory() as tmpdirname:
        shutil.copytree(
            repo.working_dir,
            os.path.join(tmpdirname, "repo_copy"),
            dirs_exist_ok=True,
        )
        repo.add_file_change_commit(
            file_name="example_should_not_exist_in_copy.txt",
            contents="""JavaScript is an amazing programming language""",
            commit_message="Add fruits data",
        )
        with temporary_cd(os.path.join(tmpdirname, "repo_copy")):
            result = runner.invoke(seagoat, [query, "."])

    assert result.exit_code == 0

    for bat_call in bat_calls:
        assert "example_should_not_exist_in_copy.txt" not in str(bat_call)

    assert [
        re.sub(r" .*repo_copy[/|\\]", " normalized_repo_path/", call)
        for call in bat_calls
    ] == snapshot

    assert len(bat_calls) == 2


def test_server_does_not_exist_error(runner_with_error, mocker, repo):
    mocker.patch(
        "seagoat.cli.requests.get",
        side_effect=requests.exceptions.ConnectionError,
    )
    query = "JavaScript"
    result = runner_with_error.invoke(seagoat, [query, repo.working_dir])

    assert result.exit_code == ExitCode.SERVER_NOT_RUNNING
    assert "The SeaGOAT server is not running" in result.stderr


@pytest.mark.usefixtures("mock_query_server")
@pytest.mark.parametrize(
    "network_error",
    [requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout],
)
def test_no_network_to_update(
    runner_with_error, mocker, mock_response, repo, network_error
):
    mocked_response = status_payload()

    mocker.patch("requests.post", return_value=mock_response(mocked_response))
    mock_running_instance(mocker)
    mocker.patch(
        "seagoat.cli.warn_if_update_available",
        side_effect=network_error,
    )
    result = runner_with_error.invoke(seagoat, ["search", repo.working_dir])

    assert result.exit_code == 0
    assert "Could not check for updates" in result.stderr


@pytest.mark.usefixtures("server", "mock_accuracy_warning")
def test_does_not_crash_with_slash_in_request(
    snapshot, repo, mocker, runner, temporary_cd
):
    mocker.patch("os.isatty", return_value=True)
    query = "JavaScript/TypeScript"

    with temporary_cd(repo.working_dir):
        result = runner.invoke(seagoat, [query, ".", "--no-color"])

    assert result.exit_code == 0


@pytest.mark.parametrize(
    "response_text",
    [
        "<html>502 Bad Gateway</html>",
        '{"message": "Not Found"}',
        '{"info": {"version": "not a version"}}',
        '{"info": null}',
    ],
)
def test_unexpected_pypi_responses_raise_errors_the_cli_handles(mocker, response_text):
    mocker.patch("requests.get", return_value=mocker.Mock(text=response_text))

    with pytest.raises((ValueError, KeyError, TypeError)):
        warn_if_update_available()


@pytest.mark.usefixtures("mock_query_server")
@pytest.mark.parametrize(
    "error",
    [
        KeyError("info"),
        ValueError("Invalid version: 'not a version'"),
        requests.exceptions.HTTPError("502"),
    ],
)
def test_unexpected_update_check_errors_do_not_fail_the_search(
    runner_with_error, mocker, mock_response, repo, error
):
    mocked_response = status_payload()

    mocker.patch("requests.post", return_value=mock_response(mocked_response))
    mock_running_instance(mocker)
    mocker.patch("seagoat.cli.warn_if_update_available", side_effect=error)
    result = runner_with_error.invoke(seagoat, ["search", repo.working_dir])

    assert result.exit_code == 0
    assert "Could not check for updates" in result.stderr


def test_server_error_message_advises_starting_the_repository(
    repo, mock_server_error_factory, runner_with_error
):
    repo_path = repo.working_dir
    error_message = (
        f"The SeaGOAT server does not serve the repository at {repo_path!r}. "
        f"Run `seagoat-server start {repo_path}` to add it to the server."
    )
    mock_server_error_factory(error_message, 404)

    result = runner_with_error.invoke(
        seagoat, [repo_path, "--no-color", "-l2", "--context=3"]
    )

    assert result.exit_code == ExitCode.SERVER_ERROR
    assert error_message in result.stderr
