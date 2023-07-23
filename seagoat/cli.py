import os
from functools import cache

import click
import requests
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import get_lexer_for_filename
from pygments.lexers.javascript import JavascriptLexer
from pygments.lexers.javascript import TypeScriptLexer

from seagoat.server import get_server_info_file
from seagoat.server import load_server_info


def query_server(query, server_address):
    response = requests.get(f"{server_address}/query/{query}")
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        print("HTTP error occurred:")
        print(f"Response code: {response.status_code}")
        print(f"Error: {err}")
        print(f"Response body: {response.text}")
        raise
    return response.json()["results"]


@cache
def get_highlighted_lines(file_name: str):
    with open(file_name, "r", encoding="utf-8") as source_code_file:
        code = source_code_file.read()

    if file_name.endswith(".md"):
        return code.splitlines()

    if file_name.endswith(".jsx"):
        lexer = JavascriptLexer()
    elif file_name.endswith(".tsx"):
        lexer = TypeScriptLexer()
    else:
        lexer = get_lexer_for_filename(file_name)

    result = highlight(code, lexer, TerminalFormatter())

    return result.splitlines()


def print_result_line(result, line, color_enabled):
    if color_enabled:
        highlighted_lines = get_highlighted_lines(str(result["full_path"]))
        print(
            f"{result['path']}:{click.style(str(line), bold=True)}:{highlighted_lines[line - 1]}"
        )
    else:
        for line_content in result["lines"]:
            if line_content["line"] == line:
                print(f"{result['path']}:{line}:{line_content['line_text']}")
                break


@click.command()
@click.argument("query")
@click.argument("repo_path", required=False, default=os.getcwd())
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable formatting. Automatically enabled when part of a bash pipeline.",
)
def seagoat(query, repo_path, no_color):
    """
    Query your codebase for your QUERY in the Git repository REPO_PATH.

    Your query can either be text that you expect to find in a file,
    or a description of what you are looking for.

    When REPO_PATH is not specified, the current working directory is
    assumed to be the repository path.
    """
    _, __, ___, server_address = load_server_info(get_server_info_file(repo_path))
    results = query_server(query, server_address)

    color_enabled = os.isatty(0) and not no_color
    for result in results:
        for result_line in result.get("lines", []):
            print_result_line(result, result_line["line"], color_enabled)


if __name__ == "__main__":
    # pylint: disable-next=no-value-for-parameter
    seagoat()
