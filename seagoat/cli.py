# pylint: disable=too-many-arguments
import math
import os
import sys
from functools import cache
from typing import Union

import click
import requests
from pydantic.typing import NoneType
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
    SERVER_ERROR = 4


def display_accuracy_warning(server_address):
    response = requests.get(
        f"{server_address}/status",
    )
    response_data = response.json()
    accuracy = response_data["stats"]["accuracy"]["percentage"]

    if accuracy < 100:
        click.echo(
            click.style(
                "Warning: SeaGOAT is still analyzing your repository. "
                + f"The results displayed have an estimated accuracy of {accuracy}%",
                fg="red",
            ),
            err=True,
        )


def query_server(
    query, server_address, repo_path, max_results, context_above, context_below
):
    try:
        response = requests.get(
            f"{server_address}/query/{query}",
            params={
                "limitClue": max_results,
                "contextAbove": context_above,
                "contextBelow": context_below,
            },
        )

        response_data = response.json()
        if "error" in response_data:
            click.echo(response_data["error"]["message"], err=True)
            sys.exit(ExitCode.SERVER_ERROR)

        response.raise_for_status()
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.RequestException,
    ):
        click.echo(
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
        highlighted_lines = get_highlighted_lines(str(result["fullPath"]))
        click.echo(
            f"{result['path']}:{click.style(str(line), bold=True)}:{highlighted_lines[line - 1]}",
            color=True,
        )
    else:
        for line_content in result["lines"]:
            if line_content["line"] == line:
                click.echo(f"{result['path']}:{line}:{line_content['lineText']}")
                break


def iterate_result_lines(results, max_results: Union[NoneType, int]):
    if max_results == 0:
        return

    lines_left_to_print = max_results if max_results is not None else math.inf

    for result in results:
        if lines_left_to_print <= 0:
            return

        for line in result.get("lines", []):
            if "result" in line["resultTypes"]:
                if lines_left_to_print <= 0:
                    return

            yield result, line

            if "result" in line["resultTypes"]:
                if max_results is not None:
                    lines_left_to_print -= 1


@click.command()
@click.argument("query")
@click.argument("repo_path", required=False, default=os.getcwd())
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable formatting. Automatically enabled when part of a bash pipeline.",
)
@click.option(
    "-l",
    "--max-results",
    type=int,
    default=None,
    help="Limit the number of result lines",
)
@click.option(
    "-B",
    "--context-above",
    type=int,
    default=None,
    help="Include this many lines of context before each result",
)
@click.option(
    "-A",
    "--context-below",
    type=int,
    default=None,
    help="Include this many lines of context after each result",
)
@click.option(
    "-C",
    "--context",
    type=int,
    default=None,
    help="Include this many lines of context after and before each result",
)
@click.version_option(version=__version__, prog_name="seagoat")
def seagoat(
    query, repo_path, no_color, max_results, context_above, context_below, context
):
    """
    Query your codebase for your QUERY in the Git repository REPO_PATH.
    Your query can contain keywords, regular expression patterns,
    or a description of what you are looking for.

    When REPO_PATH is not specified, the current working directory is
    assumed to be the repository path.

    In order to use seagoat in your repository, you need to run a server
    that will analyze your codebase. Check seagoat-server --help for more details.
    """
    server_info_file = get_server_info_file(repo_path)
    _, __, ___, server_address = load_server_info(server_info_file)

    if context is not None:
        context_above = context
        context_below = context

    results = query_server(
        query,
        server_address,
        repo_path,
        max_results,
        context_above or 0,
        context_below or 0,
    )

    color_enabled = os.isatty(0) and not no_color

    for result, result_line in iterate_result_lines(results, max_results):
        print_result_line(result, result_line["line"], color_enabled)

    display_accuracy_warning(server_address)


if __name__ == "__main__":
    # pylint: disable-next=no-value-for-parameter
    seagoat()
