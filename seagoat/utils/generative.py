from seagoat.utils.cli_display import iterate_result_blocks
from seagoat.utils.llm_provider import is_thinking_model, stream_chat


def get_spinner_text(full_raw_response):
    return (
        full_raw_response.replace("\n", " ")[-200:]
        .replace("<think>", " ")
        .replace("</think>", " ")
    )


def get_prompt(serialized_results, query):
    return f"""
Context:
{serialized_results}

You are an assistant that helps the user find code in the codebase who always responds in the following format:
Make sure to explicitly mention the full file path of each file that is important for the user query.

The user query: {query}
        """.strip()


def _strip_thinking_tags(text):
    """Remove <think>...</think> blocks from reasoning model output."""
    if "</think>" in text:
        return text.split("</think>")[-1]
    return text


def enhance_results(query, results, spinner, config=None):
    if config is None:
        config = {}

    serialized_results = ""
    results = list(results)

    for result, block in iterate_result_blocks(results, max_results=None):
        start_line = block["lines"][0]["line"]
        end_line = block["lines"][-1]["line"]
        serialized_results += f"{result['path']}:{start_line}:{end_line}\n"
        for line in block["lines"]:
            serialized_results += f"{line['lineText']}\n"

        serialized_results += "\n"

    messages = [
        {
            "role": "user",
            "content": get_prompt(serialized_results, query),
        },
    ]

    full_raw_response = ""
    for chunk_text in stream_chat(config, messages):
        full_raw_response += chunk_text
        spinner.text = get_spinner_text(full_raw_response)

    if is_thinking_model(config):
        response_text = _strip_thinking_tags(full_raw_response)
    else:
        response_text = full_raw_response

    new_results = []
    for result in results:
        if result["path"] in response_text:
            new_results.append(result)

    return new_results
