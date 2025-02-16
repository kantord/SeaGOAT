from ollama import chat
from seagoat.utils.cli_display import iterate_result_blocks


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


def enhance_results(query, results, spinner):
    serialized_results = ""
    results = list(results)

    for result, block in iterate_result_blocks(results, max_results=None):
        start_line = block["lines"][0]["line"]
        end_line = block["lines"][-1]["line"]
        serialized_results += f"{result['path']}:{start_line}:{end_line}\n"
        for line in block["lines"]:
            serialized_results += f"{line['lineText']}\n"

        serialized_results += "\n"

    response = chat(
        model="deepseek-r1:8b",
        stream=True,
        messages=[
            {
                "role": "user",
                "content": get_prompt(serialized_results, query),
            },
        ],
    )
    full_raw_response = ""
    for chunk in response:
        chunk_text = chunk["message"]["content"]
        full_raw_response += chunk_text
        spinner.text = get_spinner_text(full_raw_response)
    response_text = (full_raw_response).split("</think>")[1]

    new_results = []
    for result in results:
        if result["path"] in response_text:
            new_results.append(result)

    return new_results
