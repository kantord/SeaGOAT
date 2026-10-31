"""Fake LLM clients for tests."""


def mock_openai_stream(mocker, *contents):
    """Patch the OpenAI-style client so it streams one chunk per content."""
    chunks = []
    for content in contents:
        chunk = mocker.MagicMock()
        chunk.choices[0].delta.content = content
        chunks.append(chunk)
    get_client = mocker.patch("seagoat.utils.llm_provider._get_openai_client")
    get_client.return_value.chat.completions.create.return_value = chunks
    return get_client


def mock_ollama_stream(mocker, *contents):
    """Patch the ollama chat function so it streams one message per content."""
    chat = mocker.MagicMock(
        return_value=[{"message": {"content": content}} for content in contents]
    )
    mocker.patch("seagoat.utils.llm_provider._get_ollama_chat", return_value=chat)
    return chat
