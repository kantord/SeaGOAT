from unittest.mock import patch

import pytest

from seagoat.server import start_server
from seagoat.utils.server import _get_server_data_file_path


@pytest.fixture(name="mock_serve")
def _mock_serve():
    # create_app would start a worker thread that outlives the test repo
    with (
        patch("seagoat.server.create_app"),
        patch("seagoat.server.update_server_info"),
        patch("seagoat.server.serve") as mock_serve,
    ):
        yield mock_serve


def test_start_server_listens_on_configured_host(repo, create_config_file, mock_serve):
    create_config_file({"server": {"host": "192.0.2.10"}}, global_config=True)

    start_server(repo.working_dir, custom_port=40123)

    mock_serve.assert_called_once()
    assert mock_serve.call_args.kwargs["host"] == "192.0.2.10"
    assert mock_serve.call_args.kwargs["port"] == 40123


def test_start_server_listens_on_localhost_by_default(repo, mock_serve):
    start_server(repo.working_dir, custom_port=40124)

    assert mock_serve.call_args.kwargs["host"] == "127.0.0.1"


def test_under_pytest_registry_lives_in_pytest_directory():
    assert _get_server_data_file_path().parent.name == "seagoat-servers-pytest"
