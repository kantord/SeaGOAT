import os
import sys
from pathlib import Path

import click
import orjson
import requests

from seagoat import __version__
from seagoat.utils.cli_display import display_results
from seagoat.utils.config import get_config_values
from seagoat.utils.server import ServerDoesNotExist, get_server_info


class ExitCode:
    SERVER_NOT_RUNNING = 3
    SERVER_ERROR = 4


def warn_if_update_available():
    response = requests.get("https://pypi.org/pypi/seagoat/json")
    latest_version = orjson.loads(response.text)["info"]["version"]
    if latest_version != __version__:
        click.echo(
            f"Warning: An updated version {latest_version} of SeaGOAT is available. You have {__version__}.",
            err=True,
        )


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


def query_server(query, server_address, max_results, context_above, context_below):
    response = requests.post(
        f"{server_address}/lines/query",
        json={
            "queryText": query,
            "limitClue": max_results,
            "contextAbove": context_above,
            "contextBelow": context_below,
        },
        headers={"Content-Type": "application/json"},
    )

    response_data = orjson.loads(response.text)

    if "error" in response_data:
        click.echo(response_data["error"]["message"], err=True)
        sys.exit(ExitCode.SERVER_ERROR)

    response.raise_for_status()

    return response_data["results"]


def rewrite_full_paths_to_use_local_path(repo_path, results):
    return [
        {
            **result,
            "fullPath": str((Path(repo_path) / result["path"]).expanduser().resolve()),
        }
        for result in results
    ]


def remove_results_from_unavailable_files(results):
    return [result for result in results if Path(result["fullPath"]).exists()]


@click.command()
@click.argument("query")
@click.argument("repo_path", required=False, default=os.getcwd())
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable formatting. Automatically enabled when part of a bash pipeline.",
)
@click.option(
    "--vimgrep",
    is_flag=True,
    help="Use a vimgrep compatible output format.",
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
@click.option(
    "-r",
    "--reverse",
    is_flag=True,
    default=False,
    help="Display results in the opposite order, with the most relevant at the bottom.",
)
@click.version_option(version=__version__, prog_name="seagoat")
def seagoat(
    query,
    repo_path,
    no_color,
    max_results,
    context_above,
    context_below,
    context,
    vimgrep,
    reverse: bool,
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
    config = get_config_values(Path(repo_path))

    try:
        if config["client"]["host"] is None:
            server_info = get_server_info(repo_path)
            server_address = server_info["address"]
        else:
            server_address = config["client"]["host"]

        if context is not None:
            context_above = context
            context_below = context

        results = query_server(
            query,
            server_address,
            max_results,
            context_above if context_above is not None else 3,
            context_below if context_below is not None else 3,
        )

        results = rewrite_full_paths_to_use_local_path(repo_path, results)
        results = remove_results_from_unavailable_files(results)
        if reverse:
            results = reversed(results)

        color_enabled = os.isatty(0) and not no_color and not vimgrep

        display_results(results, max_results, color_enabled, vimgrep)

        display_accuracy_warning(server_address)
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.RequestException,
        ServerDoesNotExist,
    ):
        click.echo(
            f"The SeaGOAT server is not running. "
            f"Please start the server using the following command:\n\n"
            f"seagoat-server start {repo_path}\n"
        )
        sys.exit(ExitCode.SERVER_NOT_RUNNING)

    try:
        warn_if_update_available()
    except requests.exceptions.ConnectionError:
        click.echo(
            "Could not check for updates because the pypi.org API is not accessible"
        )


if __name__ == "__main__":
    seagoat()
