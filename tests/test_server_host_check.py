from unittest.mock import MagicMock

import pytest

from seagoat.projects import Projects
from seagoat.server import create_app


@pytest.fixture(name="create_client")
def _create_client(repo):
    def _create(host):
        mock_queue = MagicMock()
        mock_queue.enqueue.return_value = {}
        projects = Projects(lambda path, config: mock_queue)
        projects.get(repo.working_dir)
        app = create_app(projects, host)
        return app.test_client()

    yield _create


@pytest.mark.parametrize(
    "host", ["localhost", "localhost:5000", "127.0.0.1:5000", "[::1]:5000"]
)
def test_accepts_requests_for_localhost(create_client, host):
    response = create_client("127.0.0.1").get("/status", headers={"Host": host})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host",
    ["evil.example", "evil.example:5000", "localhost.evil.example", "127.0.0.1.nip.io"],
)
def test_rejects_requests_for_other_hosts(create_client, host):
    response = create_client("127.0.0.1").get("/status", headers={"Host": host})

    assert response.status_code == 403


def test_accepts_any_host_when_hosted_for_other_computers(create_client):
    response = create_client("0.0.0.0").get(  # nosec B104 - no bind, a Host header check
        "/status", headers={"Host": "seagoat.example"}
    )

    assert response.status_code == 200
