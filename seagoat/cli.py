# pylint: disable=too-many-arguments
import os
import sys

import click
import orjson
import requests

from seagoat import __version__
from seagoat.utils.cli_display import display_results
from seagoat.utils.server import get_server_info_file
from seagoat.utils.server import load_server_info


# pylint: disable-next=too-few-public-methods
class ExitCode:
    SERVER_NOT_RUNNING = 3
    SERVER_ERROR = 4


def display_accuracy_warning(server_address):
    response = requests.get(
        f"{server_address}/status",
    )
    response_data = orjson.loads(response.text)
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

        response_data = orjson.loads(response.text)
        if "error" in response_data:
            click.echo(response_data["error"]["message"], err=True)
            sys.exit(ExitCode.SERVER_ERROR)

        response.raise_for_status()
        return response_data["results"]
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

    display_results(results, max_results, color_enabled)

    display_accuracy_warning(server_address)


if __name__ == "__main__":
    # pylint: disable-next=no-value-for-parameter
    seagoat()
