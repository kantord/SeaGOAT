"""Integration tests for the LLM provider system."""

from pathlib import Path

import jsonschema
import pytest
from jsonschema.exceptions import ValidationError

from seagoat.utils.config import CONFIG_SCHEMA, get_config_values
from seagoat.utils.generative import enhance_results
from seagoat.utils.llm_provider import stream_chat
from tests.fixtures.llm import mock_openai_stream


def test_minimax_config_validates():
    config = {
        "generative": {
            "provider": "minimax",
            "model": "MiniMax-M2.5",
            "apiKey": "test-key",
            "baseUrl": "https://api.minimax.io/v1",
            "temperature": 0.5,
        }
    }
    jsonschema.validate(instance=config, schema=CONFIG_SCHEMA)


def test_openai_config_validates():
    config = {
        "generative": {
            "provider": "openai",
            "model": "gpt-4o-mini",
        }
    }
    jsonschema.validate(instance=config, schema=CONFIG_SCHEMA)


def test_ollama_config_validates():
    config = {
        "generative": {
            "provider": "ollama",
            "model": "llama3:8b",
        }
    }
    jsonschema.validate(instance=config, schema=CONFIG_SCHEMA)


def test_invalid_provider_fails_validation():
    config = {
        "generative": {
            "provider": "invalid_provider",
        }
    }
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=config, schema=CONFIG_SCHEMA)


def test_generative_config_from_global_file(repo, create_config_file):
    create_config_file(
        {"generative": {"provider": "minimax", "model": "MiniMax-M2.7"}},
        global_config=True,
    )
    config = get_config_values(Path(repo.working_dir))
    assert config["generative"]["provider"] == "minimax"
    assert config["generative"]["model"] == "MiniMax-M2.7"


def test_generative_config_in_repo_file_is_ignored(repo, create_config_file, caplog):
    create_config_file(
        {
            "generative": {
                "provider": "openai",
                "baseUrl": "https://evil.example/v1",
            }
        },
        global_config=False,
    )
    config = get_config_values(Path(repo.working_dir))
    assert config["generative"]["provider"] is None
    assert config["generative"]["baseUrl"] is None
    assert "Ignoring 'generative'" in caplog.text


def test_default_generative_config(repo):
    config = get_config_values(Path(repo.working_dir))
    assert config["generative"]["provider"] is None
    assert config["generative"]["model"] is None


def test_minimax_enhance_results(mocker):
    get_client = mock_openai_stream(mocker, "The relevant file is ", "main.py")

    config = {"generative": {"provider": "minimax", "apiKey": "test-key"}}
    spinner = mocker.MagicMock()
    results = [
        {
            "path": "main.py",
            "fullPath": "/repo/main.py",
            "blocks": [
                {
                    "lines": [
                        {"line": 1, "lineText": "def main():"},
                        {"line": 2, "lineText": "    pass"},
                    ],
                    "lineTypeCount": {"result": 2, "context": 0},
                }
            ],
        },
        {
            "path": "test.py",
            "fullPath": "/repo/test.py",
            "blocks": [
                {
                    "lines": [
                        {"line": 1, "lineText": "import unittest"},
                    ],
                    "lineTypeCount": {"result": 1, "context": 0},
                }
            ],
        },
    ]

    filtered = enhance_results("find main function", results, spinner, config)

    assert len(filtered) == 1
    assert filtered[0]["path"] == "main.py"
    get_client.assert_called_once_with("https://api.minimax.io/v1", "test-key")


def test_minimax_streams_with_temperature(mocker):
    get_client = mock_openai_stream(mocker, "response")

    config = {
        "generative": {
            "provider": "minimax",
            "apiKey": "key",
            "temperature": 0.5,
        }
    }
    messages = [{"role": "user", "content": "test"}]

    list(stream_chat(config, messages))

    call_kwargs = get_client.return_value.chat.completions.create.call_args[1]
    assert call_kwargs["temperature"] == 0.5
    assert call_kwargs["stream"] is True
    assert call_kwargs["model"] == "MiniMax-M2.5"


def test_switch_to_minimax(mocker):
    get_client = mock_openai_stream(mocker, "ok")

    config = {"generative": {"provider": "minimax", "apiKey": "key"}}
    list(stream_chat(config, [{"role": "user", "content": "q"}]))

    get_client.assert_called_once_with("https://api.minimax.io/v1", "key")


def test_switch_to_ollama(mocker):
    mocker.patch.dict("os.environ", {}, clear=True)
    chat = mocker.MagicMock(return_value=[{"message": {"content": "ok"}}])
    mocker.patch("seagoat.utils.llm_provider._get_ollama_chat", return_value=chat)

    config = {"generative": {"provider": "ollama", "model": "llama3:8b"}}
    list(stream_chat(config, [{"role": "user", "content": "q"}]))

    chat.assert_called_once()
