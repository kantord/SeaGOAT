"""Tests for the LLM provider module."""

from unittest.mock import MagicMock, patch

import pytest

from seagoat.utils.llm_provider import (
    PROVIDER_DEFAULTS,
    SUPPORTED_PROVIDERS,
    _detect_provider,
    _get_provider_config,
    is_thinking_model,
    stream_chat,
)


class TestSupportedProviders:
    def test_ollama_is_supported(self):
        assert "ollama" in SUPPORTED_PROVIDERS

    def test_openai_is_supported(self):
        assert "openai" in SUPPORTED_PROVIDERS

    def test_minimax_is_supported(self):
        assert "minimax" in SUPPORTED_PROVIDERS


class TestProviderDefaults:
    def test_ollama_has_default_model(self):
        assert "model" in PROVIDER_DEFAULTS["ollama"]

    def test_openai_has_default_model(self):
        assert "model" in PROVIDER_DEFAULTS["openai"]

    def test_minimax_has_default_model(self):
        assert PROVIDER_DEFAULTS["minimax"]["model"] == "MiniMax-M2.5"

    def test_minimax_has_base_url(self):
        assert PROVIDER_DEFAULTS["minimax"]["base_url"] == "https://api.minimax.io/v1"


class TestDetectProvider:
    @patch.dict("os.environ", {}, clear=True)
    def test_defaults_to_ollama(self):
        assert _detect_provider() == "ollama"

    @patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"}, clear=True)
    def test_detects_minimax_from_env(self):
        assert _detect_provider() == "minimax"

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True)
    def test_detects_openai_from_env(self):
        assert _detect_provider() == "openai"

    @patch.dict(
        "os.environ",
        {"MINIMAX_API_KEY": "mm-key", "OPENAI_API_KEY": "oa-key"},
        clear=True,
    )
    def test_minimax_takes_priority_over_openai(self):
        assert _detect_provider() == "minimax"


class TestGetProviderConfig:
    def test_uses_explicit_provider(self):
        config = {"generative": {"provider": "minimax"}}
        provider, model, _ = _get_provider_config(config)
        assert provider == "minimax"
        assert model == "MiniMax-M2.5"

    def test_uses_explicit_model(self):
        config = {"generative": {"provider": "minimax", "model": "MiniMax-M2.7"}}
        _, model, _ = _get_provider_config(config)
        assert model == "MiniMax-M2.7"

    def test_raises_for_unknown_provider(self):
        config = {"generative": {"provider": "unknown"}}
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            _get_provider_config(config)

    @patch.dict("os.environ", {}, clear=True)
    def test_defaults_to_ollama_when_no_config(self):
        provider, model, _ = _get_provider_config({})
        assert provider == "ollama"
        assert model == "deepseek-r1:8b"

    def test_returns_generative_config(self):
        config = {"generative": {"provider": "openai", "apiKey": "sk-test"}}
        _, _, gen_config = _get_provider_config(config)
        assert gen_config["apiKey"] == "sk-test"


class TestIsThinkingModel:
    def test_deepseek_r1_is_thinking(self):
        config = {"generative": {"provider": "ollama", "model": "deepseek-r1:8b"}}
        assert is_thinking_model(config) is True

    def test_gpt4o_is_not_thinking(self):
        config = {"generative": {"provider": "openai", "model": "gpt-4o-mini"}}
        assert is_thinking_model(config) is False

    def test_minimax_is_not_thinking(self):
        config = {"generative": {"provider": "minimax", "model": "MiniMax-M2.5"}}
        assert is_thinking_model(config) is False

    @patch.dict("os.environ", {}, clear=True)
    def test_default_ollama_is_thinking(self):
        assert is_thinking_model({}) is True


class TestStreamChatOllama:
    @patch("seagoat.utils.llm_provider._get_ollama_chat")
    @patch.dict("os.environ", {}, clear=True)
    def test_calls_ollama_chat(self, mock_get_chat):
        mock_chat = MagicMock()
        mock_chat.return_value = [
            {"message": {"content": "hello"}},
            {"message": {"content": " world"}},
        ]
        mock_get_chat.return_value = mock_chat

        config = {"generative": {"provider": "ollama"}}
        messages = [{"role": "user", "content": "test"}]

        result = list(stream_chat(config, messages))

        mock_chat.assert_called_once_with(
            model="deepseek-r1:8b", stream=True, messages=messages
        )
        assert result == ["hello", " world"]

    @patch("seagoat.utils.llm_provider._get_ollama_chat")
    @patch.dict("os.environ", {}, clear=True)
    def test_uses_custom_model(self, mock_get_chat):
        mock_chat = MagicMock()
        mock_chat.return_value = [{"message": {"content": "ok"}}]
        mock_get_chat.return_value = mock_chat

        config = {"generative": {"provider": "ollama", "model": "llama3:8b"}}
        messages = [{"role": "user", "content": "test"}]

        list(stream_chat(config, messages))

        mock_chat.assert_called_once_with(
            model="llama3:8b", stream=True, messages=messages
        )


class TestStreamChatMiniMax:
    @patch("seagoat.utils.llm_provider._get_openai_client")
    def test_calls_minimax_api(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = "result"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        config = {"generative": {"provider": "minimax", "apiKey": "test-key"}}
        messages = [{"role": "user", "content": "test"}]

        result = list(stream_chat(config, messages))

        mock_get_client.assert_called_once_with(
            "https://api.minimax.io/v1", "test-key"
        )
        assert result == ["result"]

    @patch("seagoat.utils.llm_provider._get_openai_client")
    def test_uses_default_minimax_model(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = "ok"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        config = {"generative": {"provider": "minimax", "apiKey": "key"}}
        list(stream_chat(config, [{"role": "user", "content": "q"}]))

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "MiniMax-M2.5"

    @patch("seagoat.utils.llm_provider._get_openai_client")
    def test_clamps_temperature(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = "ok"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        config = {
            "generative": {
                "provider": "minimax",
                "apiKey": "key",
                "temperature": 0.0,
            }
        }
        list(stream_chat(config, [{"role": "user", "content": "q"}]))

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] >= 0.01

    @patch("seagoat.utils.llm_provider._get_openai_client")
    @patch.dict("os.environ", {"MINIMAX_API_KEY": "env-key"}, clear=True)
    def test_reads_api_key_from_env(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = "ok"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        config = {"generative": {"provider": "minimax"}}
        list(stream_chat(config, [{"role": "user", "content": "q"}]))

        mock_get_client.assert_called_once_with(
            "https://api.minimax.io/v1", "env-key"
        )

    @patch("seagoat.utils.llm_provider._get_openai_client")
    def test_config_api_key_overrides_env(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = "ok"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        config = {"generative": {"provider": "minimax", "apiKey": "cfg-key"}}
        list(stream_chat(config, [{"role": "user", "content": "q"}]))

        mock_get_client.assert_called_once_with(
            "https://api.minimax.io/v1", "cfg-key"
        )

    @patch("seagoat.utils.llm_provider._get_openai_client")
    def test_custom_base_url(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = "ok"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        config = {
            "generative": {
                "provider": "minimax",
                "apiKey": "key",
                "baseUrl": "https://custom.api/v1",
            }
        }
        list(stream_chat(config, [{"role": "user", "content": "q"}]))

        mock_get_client.assert_called_once_with("https://custom.api/v1", "key")


class TestStreamChatOpenAI:
    @patch("seagoat.utils.llm_provider._get_openai_client")
    def test_calls_openai_api(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = "hello"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        config = {"generative": {"provider": "openai", "apiKey": "sk-test"}}
        messages = [{"role": "user", "content": "test"}]

        result = list(stream_chat(config, messages))

        mock_get_client.assert_called_once_with(
            "https://api.openai.com/v1", "sk-test"
        )
        assert result == ["hello"]

    @patch("seagoat.utils.llm_provider._get_openai_client")
    def test_default_openai_model(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = "ok"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        config = {"generative": {"provider": "openai", "apiKey": "sk-test"}}
        list(stream_chat(config, [{"role": "user", "content": "q"}]))

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"


class TestStreamChatNoneContent:
    @patch("seagoat.utils.llm_provider._get_ollama_chat")
    @patch.dict("os.environ", {}, clear=True)
    def test_handles_empty_chunks(self, mock_get_chat):
        mock_chat = MagicMock()
        mock_chat.return_value = [
            {"message": {"content": "hello"}},
            {"message": {"content": ""}},
            {"message": {"content": " world"}},
        ]
        mock_get_chat.return_value = mock_chat

        config = {"generative": {"provider": "ollama"}}
        result = list(stream_chat(config, [{"role": "user", "content": "q"}]))
        assert result == ["hello", "", " world"]
