import itertools
from typing import List

import pytest
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


@pytest.mark.parametrize("max_length", [1, 2, 10])
def test_forwards_limit_clue_to_server(max_length, get_request_args_from_cli_call):
    request_args = get_request_args_from_cli_call(["--max-results", str(max_length)])
    assert request_args["params"]["limitClue"] == max_length


@pytest.mark.usefixtures("server")
def test_integration_test_with_color(snapshot, repo, mocker, runner):
    mocker.patch("os.isatty", return_value=True)
    query = "JavaScript"
    result = runner.invoke(seagoat, [query, repo.working_dir])

    assert result.output == snapshot
    assert result.exit_code == 0


@pytest.mark.usefixtures("server")
def test_integration_test_without_color(snapshot, repo, mocker, runner):
    mocker.patch("os.isatty", return_value=True)
    query = "JavaScript"
    result = runner.invoke(seagoat, [query, repo.working_dir, "--no-color"])

    assert result.output == snapshot
    assert result.exit_code == 0


@pytest.mark.parametrize(
    "max_length, command_option",
    list(itertools.product([0, 1, 2, 20], ["--max-results", "-l"])),
)
def test_limit_output_length(
    repo, max_length, command_option, mock_server_factory, runner
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

    assert result.output.splitlines() == result.output.splitlines()[:max_length]
    assert len(result.output.splitlines()) == min(max_length, 15)
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


@pytest.mark.parametrize("context", [1, 2, 10])
def test_forwards_context_to_server(context, get_request_args_from_cli_call):
    request_args1 = get_request_args_from_cli_call(["--context", str(context)])
    assert request_args1["params"]["contextAbove"] == context
    assert request_args1["params"]["contextBelow"] == context

    request_args2 = get_request_args_from_cli_call([f"-C{context}"])
    assert request_args2["params"]["contextAbove"] == context
    assert request_args2["params"]["contextBelow"] == context


def test_limit_does_not_apply_to_context_lines(repo, mock_server_factory, runner):
    mock_server_factory(
        [
            ["hello.txt", ["foo", "a context line", "baz"]],
            ["foobar.py", ["def hello():", "    print('world')"]],
            ["foobar2.py", ["def hola():", "    print('mundo') # I am a context line"]],
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
        [query, repo.working_dir, "--no-color", "-l3", "--context=3"],
    )

    assert len(result.output.splitlines()) > 3
    assert result.exit_code == 0


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
