"""Tests for the generative search enhancement module."""

from seagoat.utils.generative import _strip_thinking_tags, enhance_results, get_prompt


def make_result(path):
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


def mock_stream_chat(mocker, *chunks):
    """Patch stream_chat so the LLM streams the given chunks."""
    return mocker.patch(
        "seagoat.utils.generative.stream_chat", return_value=iter(chunks)
    )


def test_prompt_includes_query():
    prompt = get_prompt("some code", "find login")
    assert "find login" in prompt


def test_prompt_includes_context():
    prompt = get_prompt("def hello():\n    pass", "hello func")
    assert "def hello():" in prompt


def test_strip_thinking_tags_strips_think_blocks():
    text = "<think>reasoning here</think>actual response"
    assert _strip_thinking_tags(text) == "actual response"


def test_strip_thinking_tags_without_tags_returns_original():
    text = "just a normal response"
    assert _strip_thinking_tags(text) == text


def test_strip_thinking_tags_handles_multiple_think_blocks():
    text = "<think>first</think><think>second</think>final"
    result = _strip_thinking_tags(text)
    assert "final" in result


def test_enhance_results_filters_results_by_llm_response(mocker):
    mock_stream_chat(mocker, "The relevant file is ", "main.py")
    spinner = mocker.MagicMock()

    results = [make_result("main.py"), make_result("utils.py")]

    filtered = enhance_results("find main", results, spinner, {})

    assert len(filtered) == 1
    assert filtered[0]["path"] == "main.py"


def test_enhance_results_strips_thinking_tags(mocker):
    mock_stream_chat(mocker, "<think>let me think</think>", "main.py is relevant")
    spinner = mocker.MagicMock()

    results = [make_result("main.py"), make_result("utils.py")]

    filtered = enhance_results("find main", results, spinner, {})

    assert len(filtered) == 1
    assert filtered[0]["path"] == "main.py"


def test_enhance_results_returns_empty_when_no_match(mocker):
    mock_stream_chat(mocker, "No relevant files found")
    spinner = mocker.MagicMock()

    results = [make_result("main.py")]

    filtered = enhance_results("find login", results, spinner, {})

    assert len(filtered) == 0


def test_enhance_results_returns_all_when_all_match(mocker):
    mock_stream_chat(mocker, "Both main.py and utils.py are relevant")
    spinner = mocker.MagicMock()

    results = [make_result("main.py"), make_result("utils.py")]

    filtered = enhance_results("find all", results, spinner, {})

    assert len(filtered) == 2


def test_enhance_results_updates_spinner_text(mocker):
    mock_stream_chat(mocker, "chunk1", "chunk2")
    spinner = mocker.MagicMock()

    results = [make_result("main.py")]
    enhance_results("query", results, spinner, {})

    assert spinner.text is not None


def test_enhance_results_passes_config_to_stream_chat(mocker):
    stream_chat = mock_stream_chat(mocker, "main.py")
    spinner = mocker.MagicMock()

    config = {"generative": {"provider": "minimax", "apiKey": "test"}}
    results = [make_result("main.py")]

    enhance_results("query", results, spinner, config)

    stream_chat.assert_called_once()
    call_args = stream_chat.call_args
    assert call_args[0][0] == config


def test_enhance_results_defaults_config_to_empty_dict(mocker):
    stream_chat = mock_stream_chat(mocker, "main.py")
    spinner = mocker.MagicMock()

    results = [make_result("main.py")]
    enhance_results("query", results, spinner)

    call_args = stream_chat.call_args
    assert call_args[0][0] == {}
