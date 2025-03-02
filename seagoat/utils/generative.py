import json
from ollama import chat
from seagoat.utils.cli_display import iterate_result_blocks


def get_spinner_text(full_raw_response):
    """
    Returns a shortened version of the latest response,
    which can be used for spinner or console feedback.
    """
    return full_raw_response.replace("\n", " ")[-200:]


def get_prompt(serialized_results, query):
    """
    This function constructs the user-facing context.
    It includes the relevant snippets and the user's query.

    We explicitly ask for a JSON structure with:
    - "answer" (the final answer for the user)
    - "files" (a list of file paths relevant to the query). It mentions also the most important line numbers.
    """
    return f"""
Context:
{serialized_results}

User Query:
{query}

Please provide your final answer in valid JSON with the following format, even if there are no results:

{{
    "answer": "<Your explanation or summary>",
    "files": [{{"path": "path/one", "lines": [34, 56]}}, {{"path": "path/two", "lines": [12, 45]}}]
}}
""".strip()


def enhance_results(query, results, spinner):
    """
    1. Serialize results into a single string (serialized_results).
    2. Provide system (common) instructions and user context (snippets + query) requesting JSON output.
    3. Capture the model's streaming output.
    4. Parse the JSON and filter original results to those paths explicitly mentioned in the response.
    """
    serialized_results = ""
    results_list = list(results)

    for result, block in iterate_result_blocks(results_list, max_results=None):
        start_line = block["lines"][0]["line"]
        end_line = block["lines"][-1]["line"]
        serialized_results += f"{result['path']}:{start_line}:{end_line}\n"
        for line in block["lines"]:
            serialized_results += f"{line['lineText']}\n"
        serialized_results += "\n"

    system_message = {
        "role": "system",
        "content": (
            "You are a helpful assistant that locates relevant code snippets from a codebase. "
            "Please follow these rules:\n"
            "1. Always mention the full file paths that are relevant to the user's query.\n"
            "2. Summarize or highlight the relevant code sections.\n"
            "3. Provide a brief explanation of how they address the user's request.\n"
            "4. If something is unclear, politely ask clarifying questions.\n"
            "\n"
            "IMPORTANT: You must respond in valid JSON (UTF-8) only, with two fields:\n"
            "  - 'answer': a string\n"
            "  - 'mentioned_paths': a list of strings\n"
        ),
    }

    user_message = {
        "role": "user",
        "content": get_prompt(serialized_results, query),
    }

    response = chat(
        model="deepseek-r1:8b",
        stream=True,
        options={"temperature": 0.1},
        messages=[system_message, user_message],
    )

    full_raw_response = ""
    for chunk in response:
        chunk_text = chunk["message"]["content"]
        full_raw_response += chunk_text
        spinner.text = get_spinner_text(full_raw_response)

    json_start = full_raw_response.find("{")
    json_end = full_raw_response.rfind("}") + 1
    raw_json = full_raw_response[json_start:json_end]
    parsed_response = json.loads(raw_json)
    files = parsed_response.get("files", [])

    new_results = []
    for result in results_list:
        lines_mentioned = set()
        for file in files:
            if result["path"] != file["path"]:
                continue

            lines_mentioned.update(file["lines"])

        if lines_mentioned:
            filtered_blocks = []

            for block in result["blocks"]:
                # add entire block if any line is mentioned
                if any(line["line"] in lines_mentioned for line in block["lines"]):
                    filtered_blocks.append(block)

            result["blocks"] = filtered_blocks
            new_results.append(result)

    return new_results
