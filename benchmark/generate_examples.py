import functools
import json
import os
import random
import subprocess
import uuid
from pathlib import Path

import click
import requests

from benchmark.utils import create_ai_persona, generate_personality

keywords_to_avoid = ["import", "require", "pass"]

queries_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "longQueries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "oneOf": [
                            {"minLength": 40, "maxLength": 250},
                        ],
                    }
                },
                "required": ["text"],
            },
            "minItems": 2,
            "maxItems": 2,
        },
        "shortQueries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "oneOf": [
                            {"minLength": 5, "maxLength": 15},
                        ],
                    }
                },
                "required": ["text"],
            },
            "minItems": 2,
            "maxItems": 2,
        },
        "mediumQueries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "oneOf": [
                            {"minLength": 10, "maxLength": 40},
                        ],
                    }
                },
                "required": ["text"],
            },
            "minItems": 2,
            "maxItems": 2,
        },
    },
    "required": ["queryTexts"],
}


@functools.cache
def fetch_repo_description(repo_path):
    # Get the remote URL from git
    remote_url = (
        subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"], cwd=repo_path
        )
        .decode()
        .strip()
    )
    if not remote_url:
        raise RuntimeError("No remote URL found for this repository.")

    repo_info = remote_url.split("git@github.com:")[1]
    owner, repo = repo_info.split("/")
    repo = repo.replace(".git", "")

    api_response = requests.get(f"https://api.github.com/repos/{owner}/{repo}")
    api_response.raise_for_status()
    description = api_response.json().get("description")

    if not description:
        raise RuntimeError("No remote URL found for this repository.")

    return description


def get_single_example(repo_path):
    cmd = [
        "git",
        "ls-tree",
        "--full-tree",
        "-r",
        "--name-only",
        "HEAD",
    ]
    all_files = subprocess.check_output(cmd, cwd=repo_path).decode("utf-8").splitlines()
    selected_files = [
        _file
        for _file in all_files
        if _file.endswith(
            tuple(
                [
                    ".rs",
                    ".go",
                    ".cpp",
                    ".c",
                    ".h",
                    ".ts",
                    ".js",
                    ".jsx",
                    ".tsx",
                    ".py",
                ]
            )
        )
    ]

    random.shuffle(selected_files)
    for _file in selected_files:
        full_path = os.path.join(repo_path, _file)
        with open(full_path, encoding="utf-8") as file:
            file_text = file.read()
            lines = file_text.splitlines()

        if 10 <= len(lines) <= 200:
            line_num = random.randint(0, len(lines) - 1)
            line_text = lines[line_num]
            line_num += 1

            stripped_line = line_text.strip()
            if not stripped_line:
                break

            if len([c for c in stripped_line if c.isalnum()]) < 3:
                break

            if any(keyword in stripped_line for keyword in keywords_to_avoid):
                break

            return {
                "path": _file,
                "lineNumber": line_num,
                "codeLine": line_text,
                "fullCode": file_text,
            }

    return get_single_example(repo_path)


def generate_example(repo_path):
    test_case = {
        "uuid": str(uuid.uuid4()),
        "repo": {
            "name": os.path.basename(repo_path),
            "description": fetch_repo_description(repo_path),
        },
        "targetCode": get_single_example(repo_path),
    }
    return test_case


@click.command()
@click.argument(
    "repo_path", type=click.Path(exists=True, dir_okay=True, file_okay=False)
)
@click.argument("api_key", type=str)
@click.option(
    "--num-examples",
    default=1,
    type=int,
    help="Number of examples to generate.",
)
def generate_examples(repo_path, api_key, num_examples):
    """Generates examples for a given repository path."""

    output_folder = Path(os.path.join(os.path.dirname(__file__), "examples"))
    ask_conversational_ai = create_ai_persona(generate_personality(), api_key)

    if not os.path.isdir(repo_path):
        click.echo(f"Error: {repo_path} is not a valid directory!")
        return

    for _ in range(num_examples):
        example_data = generate_example(repo_path)
        example_folder = output_folder / example_data["uuid"]

        os.makedirs(example_folder, exist_ok=True)

        file_purpose_speculation = ask_conversational_ai(
            [
                f"You are working on the project called {example_data['repo']['name']}.",
                f"The GitHub description of this project is: {example_data['repo']['description']}.",
                "Assuming you have deep knowledge of coding patterns and practices:",
                f"Think about this file path: '{example_data['targetCode']['path']}' and describe what you think this file is for in the following format:",
                "Usage: <What it's used for>",
                "Context: <Where it's located>",
                "File type: <Is it a test, boilerplate code or real implementation code. Or a database migration script>",
                "Authos: <Probably human written code vs. probably machine generated code>",
                "Be very concise",
            ]
        )["text"]

        file_purpose_speculation = ask_conversational_ai(
            [
                "There is a file that has been speculatively describe as such:",
                file_purpose_speculation,
                "The content of the file is this:",
                "```",
                example_data["targetCode"]["fullCode"],
                "```",
                "Please describe the purpose of this code FILE in the following format:",
                "Purpose: <What it does>",
                "Type: <What it is>",
                "Usage: <What it is used for>",
                "Be specific, as there might be a lot of similar lines in this code!",
                "After the description of the file, focus on the following line:",
                "```",
                example_data["targetCode"]["codeLine"],
                "```",
            ]
        )["text"]

        code_line_with_context = "\n".join(
            line
            for i, line in enumerate(
                example_data["targetCode"]["fullCode"].split("\n"), start=1
            )
            if abs(i - example_data["targetCode"]["lineNumber"]) <= 3
        )

        line_purpose_speculation = ask_conversational_ai(
            [
                "In our codebase, there is a file that can be described as such:",
                file_purpose_speculation,
                "Here is a fragment from the same file:",
                code_line_with_context,
                "The important line from this fragment is:",
                example_data["targetCode"]["codeLine"],
                """Please describe the purpose of this code FILE in the following format:
Purpose: <What it does>
Type: <What it is>
Usage: <What it is used for>
Context: <The context in which it's used>
Implementation: <How it works>
                """,
            ]
        )["text"]

        sanitized_line_purpose_speculation = ask_conversational_ai(
            [
                "There is a code line that was described as such:",
                line_purpose_speculation,
                "Keep in mind that people don't have access to our codebase as it is secret.",
                "Rewrite the same description, but remove references to code fragments or symbol names please.",
                "Remove all variable names, function names, etc from the description, but you are allowed to use synonyms.",
                "Make sure to stay specific, as there might be similar files in the project. But do not mention the specific code line.",
            ]
        )["text"]

        queries = ask_conversational_ai(
            [
                "Imagine that you are in a pub quiz. In this pub quiz, you have to instruct an AI to find code lines in a codebase.",
                "While you don't know this codebase, you receive a short description of the code lines.",
                "Your objective is to describe what you are looking for in such a way that the AI can find the code line.",
                "This is the description of the code you are looking for:",
                sanitized_line_purpose_speculation,
                "We need 6 queries (2 short, 2 medium, 3 long) that are descriptive and have a good chance of finding the specific line.",
            ],
            schema=queries_schema,
            function_name="query",
        )

        queries = ask_conversational_ai(
            [
                "These are queries for an AI based code search engine:",
                "```",
                queries,
                "```",
                "Please improve these queries by rewriting the ones that are not specific enough and don't have a good chance for finding the results!",
            ],
            schema=queries_schema,
            function_name="query",
        )

        queries = json.loads(queries)  # type: ignore
        final_queries = set()
        for query_set in queries.values():
            for query_item in query_set:
                final_queries.add(query_item["text"])

        full_example = {
            **example_data,
            "queries": list(sorted(final_queries)),
        }
        del full_example["targetCode"]["fullCode"]
        del full_example["targetCode"]["codeLine"]

        with open(
            example_folder / "example.json", "w", encoding="utf-8"
        ) as output_file:
            json.dump(full_example, output_file, indent=4)


if __name__ == "__main__":
    generate_examples()
