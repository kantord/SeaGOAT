from typing import List

import pytest
import requests
from click.testing import CliRunner
from flask import json

from seagoat import __version__
from seagoat.cli import seagoat
from seagoat.server import get_server_info_file


@pytest.fixture(name="get_request_args_from_cli_call")
def get_request_args_from_cli_call_(mock_server_factory, mocker, runner, repo):
    def _run_cli(cli_args: List[str]):
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
            mock_response.json.return_value = {"results": []}

            request_args["url"] = args[0]
            request_args["params"] = kwargs.get("params", {})

            return mock_response

        mocked_requests_get = mocker.patch(
            "seagoat.cli.requests.get", side_effect=fake_requests
        )
        query = "JavaScript"
        result = runner.invoke(
            seagoat,
            [query, repo.working_dir, "--no-color", *cli_args],
        )
        assert result.exit_code == 0
        mocked_requests_get.assert_called_once()

        return request_args

    return _run_cli


@pytest.fixture(name="mock_response")
def mock_response_(mocker):
    def _mock_response(json_data, status_code=200):
        mock_resp = mocker.Mock(spec=requests.Response)
        mock_resp.status_code = status_code
        mock_resp.json = mocker.Mock(return_value=json_data)
        return mock_resp

    return _mock_response


@pytest.fixture
def mock_accuracy_warning(mocker):
    # pylint: disable-next=unused-argument
    def _noop(*args, **kwargs):
        pass

    mocker.patch("seagoat.cli.display_accuracy_warning", _noop)


@pytest.fixture
def mock_query_server(mocker):
    # pylint: disable-next=unused-argument
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
    mock_status_response = {
        "stats": {
            "chunks": {"analyzed": 100, "unanalyzed": 0},
            "queue": {"size": 0},
            "accuracy": {"percentage": accuracy_percentage},
        },
        "version": __version__,
    }

    mocker.patch("requests.get", return_value=mock_response(mock_status_response))
    mocker.patch("seagoat.cli.get_server_info_file")
    mocker.patch("seagoat.cli.load_server_info", return_value=(None, None, None, ""))

    query = "some random query"
    result = runner_with_error.invoke(seagoat, [query, "--no-color"])

    if accuracy_percentage < 100:
        assert (
            "Warning: SeaGOAT is still analyzing your repository. "
            + f"The results displayed have an estimated accuracy of {accuracy_percentage}%"
            in result.stderr
        )
    else:
        assert "Warning" not in result.stderr


@pytest.mark.usefixtures("mock_accuracy_warning")
@pytest.mark.parametrize("max_length", [1, 2, 10])
def test_forwards_limit_clue_to_server(max_length, get_request_args_from_cli_call):
    request_args = get_request_args_from_cli_call(["--max-results", str(max_length)])
    assert request_args["params"]["limitClue"] == max_length


@pytest.mark.usefixtures("server", "mock_accuracy_warning")
def test_integration_test_with_color(snapshot, repo, mocker, runner):
    mocker.patch("os.isatty", return_value=True)
    query = "JavaScript"
    result = runner.invoke(seagoat, [query, repo.working_dir])

    assert result.output == snapshot
    assert result.exit_code == 0


@pytest.mark.usefixtures("server", "mock_accuracy_warning")
def test_integration_test_without_color(snapshot, repo, mocker, runner):
    mocker.patch("os.isatty", return_value=True)
    query = "JavaScript"
    result = runner.invoke(seagoat, [query, repo.working_dir, "--no-color"])

    assert result.output == snapshot
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
# pylint: disable-next=too-many-arguments
def test_limit_output_length(
    repo, max_length, command_option, mock_server_factory, runner, expected_length
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
        [query, repo.working_dir, "--no-color", command_option, str(max_length)],
    )

    assert len(result.output.splitlines()) == min(expected_length, 15)
    assert result.output.splitlines() == result.output.splitlines()[:expected_length]
    assert result.exit_code == 0


def test_version_option(runner):
    result = runner.invoke(seagoat, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"seagoat, version {__version__}"


@pytest.mark.parametrize(
    "repo_path",
    [
        ("/path/to/repo1"),
        ("/another/path/to/repo2"),
    ],
)
def test_server_is_not_running_error(mocker, repo_path, snapshot):
    runner = CliRunner()
    server_info_file = get_server_info_file(repo_path)
    with open(server_info_file, "w", encoding="utf-8") as file:
        json.dump({"host": "localhost", "port": 345435, "pid": 234234}, file)
    mocker.patch("os.isatty", return_value=True)
    query = "JavaScript"
    result = runner.invoke(seagoat, [query, repo_path])

    assert result.exit_code == 3
    assert result.output == snapshot


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
    assert request_args1["params"]["contextAbove"] == context_above

    request_args2 = get_request_args_from_cli_call([f"-B{context_above}"])
    assert request_args2["params"]["contextAbove"] == context_above


@pytest.mark.usefixtures("mock_accuracy_warning")
@pytest.mark.parametrize("context_below", [1, 2, 10])
def test_forwards_context_below_to_server(
    context_below, get_request_args_from_cli_call
):
    request_args1 = get_request_args_from_cli_call(
        ["--context-below", str(context_below)]
    )
    assert request_args1["params"]["contextBelow"] == context_below

    request_args2 = get_request_args_from_cli_call([f"-A{context_below}"])
    assert request_args2["params"]["contextBelow"] == context_below


@pytest.mark.usefixtures("mock_accuracy_warning")
@pytest.mark.parametrize("context", [1, 2, 10])
def test_forwards_context_to_server(context, get_request_args_from_cli_call):
    request_args1 = get_request_args_from_cli_call(["--context", str(context)])
    assert request_args1["params"]["contextAbove"] == context
    assert request_args1["params"]["contextBelow"] == context

    request_args2 = get_request_args_from_cli_call([f"-C{context}"])
    assert request_args2["params"]["contextAbove"] == context
    assert request_args2["params"]["contextBelow"] == context


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
                ["fn hello()", "    echo('world') // I am also a context line"],
            ],
            ["foobar2.fake", ["fn hola()", "    echo('mundo')"]],
            [
                "foobar3.fake",
                ["fn bonjour()", "    echo('monde') /* I am too a context line */"],
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


@pytest.mark.parametrize(
    "error_message, error_code",
    [("File Not Found on Server", 500), ("Database Connection Failed", 503)],
)
def test_server_error_handling(
    repo, mock_server_error_factory, runner_with_error, error_message, error_code
):
    mock_server_error_factory(error_message, error_code)

    query = "JavaScript"
    result = runner_with_error.invoke(
        seagoat,
        [query, repo.working_dir, "--no-color", "-l2", "--context=3"],
    )

    assert result.exit_code == 4
    assert error_message in result.stderr
