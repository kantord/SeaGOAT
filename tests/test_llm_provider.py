"""Tests for the LLM provider module."""

import pytest

from seagoat.utils.llm_provider import (
    PROVIDER_DEFAULTS,
    SUPPORTED_PROVIDERS,
    _get_provider_config,
    stream_chat,
)
from tests.fixtures.llm import mock_ollama_stream, mock_openai_stream


def test_ollama_is_supported():
    assert "ollama" in SUPPORTED_PROVIDERS


def test_openai_is_supported():
    assert "openai" in SUPPORTED_PROVIDERS


def test_minimax_is_supported():
    assert "minimax" in SUPPORTED_PROVIDERS


def test_ollama_has_default_model():
    assert "model" in PROVIDER_DEFAULTS["ollama"]


def test_openai_has_default_model():
    assert "model" in PROVIDER_DEFAULTS["openai"]


def test_minimax_has_default_model():
    assert PROVIDER_DEFAULTS["minimax"]["model"] == "MiniMax-M2.5"


def test_minimax_has_base_url():
    assert PROVIDER_DEFAULTS["minimax"]["base_url"] == "https://api.minimax.io/v1"


def test_provider_config_uses_explicit_provider():
    config = {"generative": {"provider": "minimax"}}
    provider, model, _ = _get_provider_config(config)
    assert provider == "minimax"
    assert model == "MiniMax-M2.5"


def test_provider_config_uses_explicit_model():
    config = {"generative": {"provider": "minimax", "model": "MiniMax-M2.7"}}
    _, model, _ = _get_provider_config(config)
    assert model == "MiniMax-M2.7"


def test_provider_config_raises_for_unknown_provider():
    config = {"generative": {"provider": "unknown"}}
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        _get_provider_config(config)


def test_provider_config_defaults_to_ollama_when_no_config(mocker):
    mocker.patch.dict("os.environ", {}, clear=True)
    provider, model, _ = _get_provider_config({})
    assert provider == "ollama"
    assert model == "deepseek-r1:8b"


def test_provider_config_returns_generative_config():
    config = {"generative": {"provider": "openai", "apiKey": "sk-test"}}
    _, _, gen_config = _get_provider_config(config)
    assert gen_config["apiKey"] == "sk-test"


def test_ollama_calls_ollama_chat(mocker):
    mocker.patch.dict("os.environ", {}, clear=True)
    chat = mock_ollama_stream(mocker, "hello", " world")

    config = {"generative": {"provider": "ollama"}}
    messages = [{"role": "user", "content": "test"}]

    result = list(stream_chat(config, messages))

    chat.assert_called_once_with(model="deepseek-r1:8b", stream=True, messages=messages)
    assert result == ["hello", " world"]


def test_ollama_uses_custom_model(mocker):
    mocker.patch.dict("os.environ", {}, clear=True)
    chat = mock_ollama_stream(mocker, "ok")

    config = {"generative": {"provider": "ollama", "model": "llama3:8b"}}
    messages = [{"role": "user", "content": "test"}]

    list(stream_chat(config, messages))

    chat.assert_called_once_with(model="llama3:8b", stream=True, messages=messages)


def test_minimax_calls_minimax_api(mocker):
    get_client = mock_openai_stream(mocker, "result")

    config = {"generative": {"provider": "minimax", "apiKey": "test-key"}}
    messages = [{"role": "user", "content": "test"}]

    result = list(stream_chat(config, messages))

    get_client.assert_called_once_with("https://api.minimax.io/v1", "test-key")
    assert result == ["result"]


def test_minimax_uses_default_model(mocker):
    get_client = mock_openai_stream(mocker, "ok")

    config = {"generative": {"provider": "minimax", "apiKey": "key"}}
    list(stream_chat(config, [{"role": "user", "content": "q"}]))

    create = get_client.return_value.chat.completions.create
    assert create.call_args[1]["model"] == "MiniMax-M2.5"


def test_minimax_clamps_temperature(mocker):
    get_client = mock_openai_stream(mocker, "ok")

    config = {
        "generative": {
            "provider": "minimax",
            "apiKey": "key",
            "temperature": 0.0,
        }
    }
    list(stream_chat(config, [{"role": "user", "content": "q"}]))

    create = get_client.return_value.chat.completions.create
    assert create.call_args[1]["temperature"] >= 0.01


def test_minimax_reads_api_key_from_env(mocker):
    mocker.patch.dict("os.environ", {"MINIMAX_API_KEY": "env-key"}, clear=True)
    get_client = mock_openai_stream(mocker, "ok")

    config = {"generative": {"provider": "minimax"}}
    list(stream_chat(config, [{"role": "user", "content": "q"}]))

    get_client.assert_called_once_with("https://api.minimax.io/v1", "env-key")


def test_minimax_config_api_key_overrides_env(mocker):
    get_client = mock_openai_stream(mocker, "ok")

    config = {"generative": {"provider": "minimax", "apiKey": "cfg-key"}}
    list(stream_chat(config, [{"role": "user", "content": "q"}]))

    get_client.assert_called_once_with("https://api.minimax.io/v1", "cfg-key")


def test_minimax_uses_custom_base_url(mocker):
    get_client = mock_openai_stream(mocker, "ok")

    config = {
        "generative": {
            "provider": "minimax",
            "apiKey": "key",
            "baseUrl": "https://custom.api/v1",
        }
    }
    list(stream_chat(config, [{"role": "user", "content": "q"}]))

    get_client.assert_called_once_with("https://custom.api/v1", "key")


def test_openai_calls_openai_api(mocker):
    get_client = mock_openai_stream(mocker, "hello")

    config = {"generative": {"provider": "openai", "apiKey": "sk-test"}}
    messages = [{"role": "user", "content": "test"}]

    result = list(stream_chat(config, messages))

    get_client.assert_called_once_with("https://api.openai.com/v1", "sk-test")
    assert result == ["hello"]


def test_openai_uses_default_model(mocker):
    get_client = mock_openai_stream(mocker, "ok")

    config = {"generative": {"provider": "openai", "apiKey": "sk-test"}}
    list(stream_chat(config, [{"role": "user", "content": "q"}]))

    create = get_client.return_value.chat.completions.create
    assert create.call_args[1]["model"] == "gpt-4o-mini"


def test_ollama_handles_empty_chunks(mocker):
    mocker.patch.dict("os.environ", {}, clear=True)
    mock_ollama_stream(mocker, "hello", "", " world")

    config = {"generative": {"provider": "ollama"}}
    result = list(stream_chat(config, [{"role": "user", "content": "q"}]))
    assert result == ["hello", "", " world"]


def test_api_keys_in_env_do_not_select_a_cloud_provider(mocker):
    mocker.patch.dict(
        "os.environ", {"OPENAI_API_KEY": "sk-env", "MINIMAX_API_KEY": "mm"}, clear=True
    )
    provider, _, _ = _get_provider_config({})
    assert provider == "ollama"


def test_minimax_with_default_config_values(mocker):
    mock_openai_stream(mocker, "hi")
    config = {
        "generative": {
            "provider": "minimax",
            "model": None,
            "apiKey": "k",
            "baseUrl": None,
            "temperature": None,
        }
    }
    assert list(stream_chat(config, [])) == ["hi"]


def test_skips_chunks_without_choices(mocker):
    get_client = mock_openai_stream(mocker, "hi")
    usage_chunk = mocker.MagicMock()
    usage_chunk.choices = []
    create = get_client.return_value.chat.completions.create
    create.return_value = [usage_chunk, *create.return_value]
    config = {"generative": {"provider": "openai", "apiKey": "k"}}
    assert list(stream_chat(config, [])) == ["hi"]
