import itertools

import pytest
from click.testing import CliRunner
from flask import json

from seagoat import __version__
from seagoat.cli import seagoat
from seagoat.server import get_server_info_file


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
