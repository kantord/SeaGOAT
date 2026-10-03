"""Tests for OrcaRouter routing through the shared LLM provider adapter."""

from unittest.mock import MagicMock, patch

import pytest

from seagoat.utils.llm_provider import (
    PROVIDER_DEFAULTS,
    SUPPORTED_PROVIDERS,
    OrcaRouterAuthError,
    _get_provider_config,
    is_thinking_model,
    stream_chat,
)

API_ORIGIN = "https://api.orcarouter.ai/v1"
AUTH_ORIGIN = "https://www.orcarouter.ai"
FAKE_KEY = "sk-orca-provider-00000000000000000000000"


def _openai_client(chunks=("ok",)):
    client = MagicMock()

    def _chunk(text):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = text
        return chunk

    client.chat.completions.create.return_value = [_chunk(text) for text in chunks]
    return client


class TestRegistration:
    def test_orcarouter_is_first_class(self):
        assert "orcarouter" in SUPPORTED_PROVIDERS
        assert "orcarouter" in PROVIDER_DEFAULTS

    def test_default_model_is_an_orcarouter_namespace(self):
        assert PROVIDER_DEFAULTS["orcarouter"]["model"] == "orcarouter/auto"

    def test_existing_providers_are_untouched(self):
        assert PROVIDER_DEFAULTS["ollama"]["model"] == "deepseek-r1:8b"
        assert PROVIDER_DEFAULTS["openai"]["model"] == "gpt-4o-mini"
        assert PROVIDER_DEFAULTS["minimax"]["model"] == "MiniMax-M2.5"


class TestApiKeyPath:
    @patch("seagoat.utils.llm_provider._get_openai_client")
    @patch.dict("os.environ", {}, clear=True)
    def test_api_key_adapter_reaches_the_inference_origin(self, mock_get_client):
        mock_get_client.return_value = _openai_client(["hello"])
        config = {"generative": {"provider": "orcarouter", "apiKey": FAKE_KEY}}

        result = list(stream_chat(config, [{"role": "user", "content": "q"}]))

        mock_get_client.assert_called_once_with(API_ORIGIN, FAKE_KEY)
        assert result == ["hello"]

    @patch("seagoat.utils.llm_provider._get_openai_client")
    @patch.dict("os.environ", {"ORCAROUTER_API_KEY": FAKE_KEY}, clear=True)
    def test_env_key_is_used(self, mock_get_client):
        mock_get_client.return_value = _openai_client(["env"])
        config = {"generative": {"provider": "orcarouter"}}

        assert list(stream_chat(config, [{"role": "user", "content": "q"}])) == ["env"]
        mock_get_client.assert_called_once_with(API_ORIGIN, FAKE_KEY)

    @patch("seagoat.utils.llm_provider._get_openai_client")
    @patch.dict("os.environ", {}, clear=True)
    def test_pkce_stored_key_is_used(self, mock_get_client, tmp_path):
        mock_get_client.return_value = _openai_client(["stored"])
        from seagoat.utils.orcarouter import store

        path = tmp_path / "config.yml"
        with patch.object(store, "config_file", return_value=path):
            store.write_record({"api_key": FAKE_KEY, "source": "pkce"})
            config = {"generative": {"provider": "orcarouter"}}
            result = list(stream_chat(config, [{"role": "user", "content": "q"}]))

        mock_get_client.assert_called_once_with(API_ORIGIN, FAKE_KEY)
        assert result == ["stored"]

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_credential_is_a_clear_error(self, tmp_path):
        from seagoat.utils.orcarouter import store

        path = tmp_path / "config.yml"
        with patch.object(store, "config_file", return_value=path):
            config = {"generative": {"provider": "orcarouter"}}
            with pytest.raises(ValueError, match="No OrcaRouter API key"):
                list(stream_chat(config, [{"role": "user", "content": "q"}]))

    @patch("seagoat.utils.llm_provider._get_openai_client")
    @patch.dict("os.environ", {}, clear=True)
    def test_api_origin_override_is_honoured(self, mock_get_client):
        mock_get_client.return_value = _openai_client(["x"])
        config = {
            "generative": {
                "provider": "orcarouter",
                "apiKey": FAKE_KEY,
                "apiBaseUrl": "https://relay.internal.example/v1",
            }
        }
        list(stream_chat(config, [{"role": "user", "content": "q"}]))
        mock_get_client.assert_called_once_with(
            "https://relay.internal.example/v1", FAKE_KEY
        )


class TestAuthError:
    @patch("seagoat.utils.llm_provider._get_openai_client")
    @patch.dict("os.environ", {}, clear=True)
    def test_401_is_terminal_without_refresh(self, mock_get_client):
        class Unauthorized(Exception):
            status_code = 401

        client = MagicMock()
        client.chat.completions.create.side_effect = Unauthorized("revoked")
        mock_get_client.return_value = client

        config = {"generative": {"provider": "orcarouter", "apiKey": FAKE_KEY}}
        with pytest.raises(OrcaRouterAuthError, match="reconnect"):
            list(stream_chat(config, [{"role": "user", "content": "q"}]))

        # A durable key is not a refresh token: exactly one attempt is made.
        assert client.chat.completions.create.call_count == 1

    @patch("seagoat.utils.llm_provider._get_openai_client")
    @patch.dict("os.environ", {}, clear=True)
    def test_other_errors_are_not_misreported(self, mock_get_client):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("transport")
        mock_get_client.return_value = client

        config = {"generative": {"provider": "orcarouter", "apiKey": FAKE_KEY}}
        with pytest.raises(RuntimeError, match="transport"):
            list(stream_chat(config, [{"role": "user", "content": "q"}]))


class TestStreamingShape:
    @patch("seagoat.utils.llm_provider._get_openai_client")
    @patch.dict("os.environ", {}, clear=True)
    def test_usage_only_final_chunk_is_skipped(self, mock_get_client):
        client = MagicMock()

        def chunk(text):
            item = MagicMock()
            item.choices = [MagicMock()]
            item.choices[0].delta.content = text
            return item

        usage_only = MagicMock()
        usage_only.choices = []
        client.chat.completions.create.return_value = [
            chunk("po"),
            usage_only,
            chunk("ng"),
        ]
        mock_get_client.return_value = client

        config = {"generative": {"provider": "orcarouter", "apiKey": FAKE_KEY}}
        assert list(stream_chat(config, [{"role": "user", "content": "q"}])) == [
            "po",
            "ng",
        ]


class TestProviderConfig:
    def test_orcarouter_model_default(self):
        provider, model, _ = _get_provider_config(
            {"generative": {"provider": "orcarouter"}}
        )
        assert provider == "orcarouter"
        assert model == "orcarouter/auto"

    def test_orcarouter_is_not_treated_as_a_thinking_model(self):
        config = {"generative": {"provider": "orcarouter"}}
        assert is_thinking_model(config) is False
