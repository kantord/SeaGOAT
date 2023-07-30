import pytest
from click.testing import CliRunner
from flask import json

from seagoat import __version__
from seagoat.cli import seagoat
from seagoat.server import get_server_info_file
from tests.conftest import pytest


@pytest.mark.usefixtures("server")
def test_integration_test_with_color(snapshot, repo, mocker):
    mocker.patch("os.isatty", return_value=True)
    runner = CliRunner()
    query = "JavaScript"
    result = runner.invoke(seagoat, [query, repo.working_dir])

    assert result.output == snapshot
    assert result.exit_code == 0


@pytest.mark.usefixtures("server")
def test_integration_test_without_color(snapshot, repo, mocker):
    mocker.patch("os.isatty", return_value=True)
    runner = CliRunner()
    query = "JavaScript"
    result = runner.invoke(seagoat, [query, repo.working_dir, "--no-color"])

    assert result.output == snapshot
    assert result.exit_code == 0


def test_version_option():
    runner = CliRunner()
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
    server_info_file = get_server_info_file(repo_path)
    with open(server_info_file, "w", encoding="utf-8") as file:
        json.dump({"host": "localhost", "port": 345435, "pid": 234234}, file)
    mocker.patch("os.isatty", return_value=True)
    runner = CliRunner()
    query = "JavaScript"
    result = runner.invoke(seagoat, [query, repo_path])

    assert result.exit_code == 3
    assert result.output == snapshot
