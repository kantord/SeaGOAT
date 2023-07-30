import os
import sys
from functools import cache

import click
import requests
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import get_lexer_for_filename
from pygments.lexers.javascript import JavascriptLexer
from pygments.lexers.javascript import TypeScriptLexer

from seagoat import __version__
from seagoat.server import get_server_info_file
from seagoat.server import load_server_info


# pylint: disable-next=too-few-public-methods
class ExitCode:
    SERVER_NOT_RUNNING = 3


def query_server(query, server_address, repo_path):
    try:
        response = requests.get(f"{server_address}/query/{query}")
        response.raise_for_status()
    except (requests.exceptions.ConnectionError, requests.exceptions.RequestException):
        print(
            f"The SeaGOAT server is not running. "
            f"Please start the server using the following command:\n\n"
            f"seagoat-server start {repo_path}\n"
        )
        sys.exit(ExitCode.SERVER_NOT_RUNNING)

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
@click.version_option(version=__version__, prog_name="seagoat")
def seagoat(query, repo_path, no_color):
    server_info_file = get_server_info_file(repo_path)
    _, __, ___, server_address = load_server_info(server_info_file)
    results = query_server(query, server_address, repo_path)

    color_enabled = os.isatty(0) and not no_color
    for result in results:
        for result_line in result.get("lines", []):
            print_result_line(result, result_line["line"], color_enabled)


if __name__ == "__main__":
    # pylint: disable-next=no-value-for-parameter
    seagoat()
