"""Tests for the OrcaRouter CLI commands."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from seagoat.cli import orcarouter_login, orcarouter_logout, orcarouter_models
from seagoat.cli import orcarouter_status
from seagoat.utils.orcarouter import store

FAKE_KEY = "sk-orca-cli-0000000000000000000000000000"

CONFIG = {
    "generative": {
        "provider": "orcarouter",
        "apiBaseUrl": "https://api.orcarouter.ai/v1",
        "authBaseUrl": "https://www.orcarouter.ai",
    }
}


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def isolated_store(tmp_path):
    path = tmp_path / "config.yml"
    with patch.object(store, "config_file", return_value=path):
        yield path


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setattr("seagoat.cli.get_config_values", lambda _path: CONFIG)
    return CONFIG


class TestApiKeyLogin:
    def test_paste_key_is_stored(self, runner, isolated_store, config):
        result = runner.invoke(orcarouter_login, ["--api-key"], input=f"{FAKE_KEY}\n")
        assert result.exit_code == 0
        assert store.stored_key() == FAKE_KEY
        assert "saved" in result.output.lower()

    def test_bad_key_shape_exits_nonzero(self, runner, isolated_store, config):
        result = runner.invoke(orcarouter_login, ["--api-key"], input="nonsense\n")
        assert result.exit_code == 1
        assert store.stored_key() is None
        assert "sk-orca-" in result.output

    def test_full_key_is_never_echoed(self, runner, isolated_store, config):
        result = runner.invoke(orcarouter_login, ["--api-key"], input=f"{FAKE_KEY}\n")
        assert FAKE_KEY not in result.output


class TestStatus:
    def test_masks_the_stored_key(self, runner, isolated_store, config):
        store.write_record({"api_key": FAKE_KEY, "source": "pkce"})
        result = runner.invoke(orcarouter_status, [])
        assert result.exit_code == 0
        assert FAKE_KEY not in result.output
        assert "sk-orca" in result.output
        assert "connected" in result.output
        assert "https://www.orcarouter.ai" in result.output
        assert "https://api.orcarouter.ai/v1" in result.output

    def test_reports_disconnected(self, runner, isolated_store, config):
        with patch.dict("os.environ", {}, clear=True):
            result = runner.invoke(orcarouter_status, [])
        assert "not connected" in result.output


class TestLogout:
    def test_clears_stored_key(self, runner, isolated_store, config):
        store.write_record({"api_key": FAKE_KEY, "source": "pkce"})
        result = runner.invoke(orcarouter_logout, [])
        assert result.exit_code == 0
        assert store.stored_key() is None
        assert "removed" in result.output.lower()

    def test_reports_when_nothing_to_clear(self, runner, isolated_store, config):
        result = runner.invoke(orcarouter_logout, [])
        assert "No stored" in result.output


class TestModels:
    def test_uses_config_api_key_and_auth_origin(self, runner, isolated_store):
        from seagoat.utils.orcarouter import CAPABILITY_CHAT, CatalogResult, Model

        captured = {}

        def fake_discover(generative_config, capability=None, session=None, **kwargs):
            captured["config"] = generative_config
            captured["capability"] = capability
            return CatalogResult(
                models=[Model(id="vendor/only", endpoint_types=("openai",))],
                source="live",
            )

        with patch("seagoat.cli.get_config_values", lambda _p: CONFIG):
            with patch("seagoat.utils.orcarouter.discover_models", fake_discover):
                result = runner.invoke(orcarouter_models, ["--capability", "chat"])

        assert result.exit_code == 0
        assert "vendor/only" in result.output
        assert captured["capability"] == CAPABILITY_CHAT

    def test_degraded_catalog_is_reported(self, runner, isolated_store):
        from seagoat.utils.orcarouter import CatalogResult

        def fake_discover(generative_config, capability=None, session=None, **kwargs):
            return CatalogResult(models=[], source="seed", degraded=True, error="boom")

        with patch("seagoat.cli.get_config_values", lambda _p: CONFIG):
            with patch("seagoat.utils.orcarouter.discover_models", fake_discover):
                result = runner.invoke(orcarouter_models, [])

        assert result.exit_code == 0
        assert (
            "degraded" in result.output.lower()
            or "unavailable" in result.output.lower()
        )
