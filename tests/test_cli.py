from click.testing import CliRunner

from seagoat.cli import seagoat
from tests.conftest import pytest


@pytest.mark.usefixtures("server")
def test_integration_test_with_color(snapshot, repo, mocker):
    mocker.patch("os.isatty", return_value=True)
    runner = CliRunner()
    query = "JavaScript"
    result = runner.invoke(seagoat, [query, repo.working_dir])

    assert result.output == snapshot
    assert result.exit_code == 0
