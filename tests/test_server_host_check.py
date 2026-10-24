import pytest

from seagoat.server import create_app


@pytest.fixture(name="create_client")
def _create_client(repo):
    apps = []

    def _create():
        app = create_app(repo.working_dir)
        apps.append(app)
        return app.test_client()

    yield _create

    for app in apps:
        app.extensions["task_queue"].shutdown()


@pytest.mark.parametrize(
    "host", ["localhost", "localhost:5000", "127.0.0.1:5000", "[::1]:5000"]
)
def test_accepts_requests_for_localhost(create_client, host):
    response = create_client().get("/status", headers={"Host": host})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host",
    ["evil.example", "evil.example:5000", "localhost.evil.example", "127.0.0.1.nip.io"],
)
def test_rejects_requests_for_other_hosts(create_client, host):
    response = create_client().get("/status", headers={"Host": host})

    assert response.status_code == 403


def test_accepts_any_host_when_hosted_for_other_computers(
    create_client, create_config_file
):
    create_config_file({"server": {"host": "0.0.0.0"}}, global_config=True)

    response = create_client().get("/status", headers={"Host": "seagoat.example"})

    assert response.status_code == 200
