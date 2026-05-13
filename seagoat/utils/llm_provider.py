"""
LLM provider abstraction for the generative search feature.

Supports multiple LLM backends:
- ollama: Local Ollama server (default, existing behavior)
- openai: OpenAI API
- minimax: MiniMax API (OpenAI-compatible)
"""

import os


PROVIDER_DEFAULTS = {
    "ollama": {
        "model": "deepseek-r1:8b",
    },
    "openai": {
        "model": "gpt-4o-mini",
    },
    "minimax": {
        "model": "MiniMax-M2.5",
        "base_url": "https://api.minimax.io/v1",
    },
}

SUPPORTED_PROVIDERS = list(PROVIDER_DEFAULTS.keys())


def _detect_provider():
    """Auto-detect provider from environment variables."""
    if os.environ.get("MINIMAX_API_KEY"):
        return "minimax"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "ollama"


def _get_provider_config(config):
    """Extract generative provider config, with auto-detection fallback."""
    generative_config = config.get("generative", {})
    provider_name = generative_config.get("provider") or _detect_provider()

    if provider_name not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider: {provider_name}. "
            f"Supported providers: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    defaults = PROVIDER_DEFAULTS[provider_name]
    model = generative_config.get("model") or defaults["model"]

    return provider_name, model, generative_config


def _get_ollama_chat():
    """Lazy import for ollama chat function."""
    from ollama import chat
    return chat


def _get_openai_client(base_url, api_key):
    """Lazy import for OpenAI client."""
    from openai import OpenAI
    return OpenAI(base_url=base_url, api_key=api_key)


def _stream_ollama(messages, model, _generative_config):
    """Stream responses from Ollama."""
    chat_fn = _get_ollama_chat()
    response = chat_fn(model=model, stream=True, messages=messages)
    for chunk in response:
        yield chunk["message"]["content"]


def _stream_openai_compat(messages, model, base_url, api_key, temperature):
    """Stream responses from an OpenAI-compatible API."""
    client = _get_openai_client(base_url, api_key)
    kwargs = {"model": model, "messages": messages, "stream": True}
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = client.chat.completions.create(**kwargs)
    for chunk in response:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


def _stream_openai(messages, model, generative_config):
    """Stream responses from OpenAI API."""
    api_key = generative_config.get("apiKey") or os.environ.get("OPENAI_API_KEY")
    base_url = generative_config.get("baseUrl") or "https://api.openai.com/v1"
    yield from _stream_openai_compat(messages, model, base_url, api_key, None)


def _stream_minimax(messages, model, generative_config):
    """Stream responses from MiniMax API (OpenAI-compatible)."""
    api_key = generative_config.get("apiKey") or os.environ.get("MINIMAX_API_KEY")
    base_url = (
        generative_config.get("baseUrl")
        or PROVIDER_DEFAULTS["minimax"]["base_url"]
    )
    temperature = max(0.01, min(1.0, generative_config.get("temperature", 0.1)))
    yield from _stream_openai_compat(messages, model, base_url, api_key, temperature)


_STREAM_HANDLERS = {
    "ollama": _stream_ollama,
    "openai": _stream_openai,
    "minimax": _stream_minimax,
}


def stream_chat(config, messages):
    """
    Stream chat completions from the configured LLM provider.

    Args:
        config: The full SeaGOAT config dict.
        messages: List of message dicts with 'role' and 'content'.

    Yields:
        str: Text chunks from the LLM response.
    """
    provider_name, model, generative_config = _get_provider_config(config)
    handler = _STREAM_HANDLERS[provider_name]
    yield from handler(messages, model, generative_config)


def is_thinking_model(config):
    """Check if the configured model is a thinking/reasoning model."""
    generative_config = config.get("generative", {})
    provider_name = generative_config.get("provider") or _detect_provider()
    model = generative_config.get("model") or PROVIDER_DEFAULTS.get(
        provider_name, {}
    ).get("model", "")

    thinking_patterns = ["deepseek-r1", "o1", "o3"]
    return any(pattern in model.lower() for pattern in thinking_patterns)
