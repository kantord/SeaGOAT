"""Tests for the generative search enhancement module."""

from unittest.mock import MagicMock, patch

from seagoat.utils.generative import _strip_thinking_tags, enhance_results, get_prompt


class TestGetPrompt:
    def test_includes_query(self):
        prompt = get_prompt("some code", "find login")
        assert "find login" in prompt

    def test_includes_context(self):
        prompt = get_prompt("def hello():\n    pass", "hello func")
        assert "def hello():" in prompt


class TestStripThinkingTags:
    def test_strips_think_blocks(self):
        text = "<think>reasoning here</think>actual response"
        assert _strip_thinking_tags(text) == "actual response"

    def test_no_think_tags_returns_original(self):
        text = "just a normal response"
        assert _strip_thinking_tags(text) == text

    def test_multiple_think_blocks(self):
        text = "<think>first</think><think>second</think>final"
        result = _strip_thinking_tags(text)
        assert "final" in result


class TestEnhanceResults:
    def _make_result(self, path):
        return {
            "path": path,
            "fullPath": f"/repo/{path}",
            "blocks": [
                {
                    "lines": [
                        {"line": 1, "lineText": f"# {path} content"},
                        {"line": 2, "lineText": "some code here"},
                    ],
                    "lineTypeCount": {"result": 2, "context": 0},
                }
            ],
        }

    @patch("seagoat.utils.generative.stream_chat")
    @patch("seagoat.utils.generative.is_thinking_model", return_value=False)
    def test_filters_results_by_llm_response(self, mock_thinking, mock_stream):
        mock_stream.return_value = iter(["The relevant file is ", "main.py"])
        spinner = MagicMock()

        results = [self._make_result("main.py"), self._make_result("utils.py")]

        filtered = enhance_results("find main", results, spinner, {})

        assert len(filtered) == 1
        assert filtered[0]["path"] == "main.py"

    @patch("seagoat.utils.generative.stream_chat")
    @patch("seagoat.utils.generative.is_thinking_model", return_value=True)
    def test_strips_thinking_for_reasoning_models(self, mock_thinking, mock_stream):
        mock_stream.return_value = iter(
            ["<think>let me think</think>", "main.py is relevant"]
        )
        spinner = MagicMock()

        results = [self._make_result("main.py"), self._make_result("utils.py")]

        filtered = enhance_results("find main", results, spinner, {})

        assert len(filtered) == 1
        assert filtered[0]["path"] == "main.py"

    @patch("seagoat.utils.generative.stream_chat")
    @patch("seagoat.utils.generative.is_thinking_model", return_value=False)
    def test_returns_empty_when_no_match(self, mock_thinking, mock_stream):
        mock_stream.return_value = iter(["No relevant files found"])
        spinner = MagicMock()

        results = [self._make_result("main.py")]

        filtered = enhance_results("find login", results, spinner, {})

        assert len(filtered) == 0

    @patch("seagoat.utils.generative.stream_chat")
    @patch("seagoat.utils.generative.is_thinking_model", return_value=False)
    def test_returns_all_when_all_match(self, mock_thinking, mock_stream):
        mock_stream.return_value = iter(
            ["Both main.py and utils.py are relevant"]
        )
        spinner = MagicMock()

        results = [self._make_result("main.py"), self._make_result("utils.py")]

        filtered = enhance_results("find all", results, spinner, {})

        assert len(filtered) == 2

    @patch("seagoat.utils.generative.stream_chat")
    @patch("seagoat.utils.generative.is_thinking_model", return_value=False)
    def test_updates_spinner_text(self, mock_thinking, mock_stream):
        mock_stream.return_value = iter(["chunk1", "chunk2"])
        spinner = MagicMock()

        results = [self._make_result("main.py")]
        enhance_results("query", results, spinner, {})

        assert spinner.text is not None

    @patch("seagoat.utils.generative.stream_chat")
    @patch("seagoat.utils.generative.is_thinking_model", return_value=False)
    def test_passes_config_to_stream_chat(self, mock_thinking, mock_stream):
        mock_stream.return_value = iter(["main.py"])
        spinner = MagicMock()

        config = {"generative": {"provider": "minimax", "apiKey": "test"}}
        results = [self._make_result("main.py")]

        enhance_results("query", results, spinner, config)

        mock_stream.assert_called_once()
        call_args = mock_stream.call_args
        assert call_args[0][0] == config

    @patch("seagoat.utils.generative.stream_chat")
    @patch("seagoat.utils.generative.is_thinking_model", return_value=False)
    def test_defaults_config_to_empty_dict(self, mock_thinking, mock_stream):
        mock_stream.return_value = iter(["main.py"])
        spinner = MagicMock()

        results = [self._make_result("main.py")]
        enhance_results("query", results, spinner)

        call_args = mock_stream.call_args
        assert call_args[0][0] == {}
