"""Integration tests for the LLM provider system."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import jsonschema
import pytest

from seagoat.utils.config import CONFIG_SCHEMA, get_config_values
from seagoat.utils.generative import enhance_results
from seagoat.utils.llm_provider import SUPPORTED_PROVIDERS, stream_chat


class TestConfigIntegration:
    """Test that generative config integrates with SeaGOAT's config system."""

    def test_minimax_config_validates(self):
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

    def test_openai_config_validates(self):
        config = {
            "generative": {
                "provider": "openai",
                "model": "gpt-4o-mini",
            }
        }
        jsonschema.validate(instance=config, schema=CONFIG_SCHEMA)

    def test_ollama_config_validates(self):
        config = {
            "generative": {
                "provider": "ollama",
                "model": "llama3:8b",
            }
        }
        jsonschema.validate(instance=config, schema=CONFIG_SCHEMA)

    def test_invalid_provider_fails_validation(self):
        config = {
            "generative": {
                "provider": "invalid_provider",
            }
        }
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance=config, schema=CONFIG_SCHEMA)

    def test_generative_config_from_file(self, repo, create_config_file):
        create_config_file(
            {"generative": {"provider": "minimax", "model": "MiniMax-M2.7"}},
            global_config=False,
        )
        config = get_config_values(Path(repo.working_dir))
        assert config["generative"]["provider"] == "minimax"
        assert config["generative"]["model"] == "MiniMax-M2.7"

    def test_default_generative_config(self, repo):
        config = get_config_values(Path(repo.working_dir))
        assert config["generative"]["provider"] is None
        assert config["generative"]["model"] is None


class TestEndToEndMiniMax:
    """Test MiniMax provider end-to-end with mocked API."""

    @patch("seagoat.utils.llm_provider._get_openai_client")
    def test_minimax_enhance_results(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_chunk1 = MagicMock()
        mock_chunk1.choices[0].delta.content = "The relevant file is "
        mock_chunk2 = MagicMock()
        mock_chunk2.choices[0].delta.content = "main.py"
        mock_client.chat.completions.create.return_value = [mock_chunk1, mock_chunk2]

        config = {"generative": {"provider": "minimax", "apiKey": "test-key"}}
        spinner = MagicMock()
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
        mock_get_client.assert_called_once_with(
            "https://api.minimax.io/v1", "test-key"
        )

    @patch("seagoat.utils.llm_provider._get_openai_client")
    def test_minimax_streams_with_temperature(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = "response"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        config = {
            "generative": {
                "provider": "minimax",
                "apiKey": "key",
                "temperature": 0.5,
            }
        }
        messages = [{"role": "user", "content": "test"}]

        list(stream_chat(config, messages))

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["stream"] is True
        assert call_kwargs["model"] == "MiniMax-M2.5"


class TestProviderSwitching:
    """Test switching between providers via config."""

    @patch("seagoat.utils.llm_provider._get_openai_client")
    def test_switch_to_minimax(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_chunk = MagicMock()
        mock_chunk.choices[0].delta.content = "ok"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        config = {"generative": {"provider": "minimax", "apiKey": "key"}}
        list(stream_chat(config, [{"role": "user", "content": "q"}]))

        mock_get_client.assert_called_once_with(
            "https://api.minimax.io/v1", "key"
        )

    @patch("seagoat.utils.llm_provider._get_ollama_chat")
    @patch.dict("os.environ", {}, clear=True)
    def test_switch_to_ollama(self, mock_get_chat):
        mock_chat = MagicMock()
        mock_chat.return_value = [{"message": {"content": "ok"}}]
        mock_get_chat.return_value = mock_chat

        config = {"generative": {"provider": "ollama", "model": "llama3:8b"}}
        list(stream_chat(config, [{"role": "user", "content": "q"}]))

        mock_chat.assert_called_once()
