import os
import sys
from pathlib import Path

import click
import orjson
import requests
from halo import Halo

from seagoat import __version__
from seagoat.utils.cli_display import display_results
from seagoat.utils.config import get_config_values
from seagoat.utils.generative import enhance_results
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
@click.option(
    "-g",
    "--generative",
    is_flag=True,
    default=False,
    help="Use a generative model to enhance results",
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
    generative: bool,
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
    spinner = Halo(text="Generating response...", spinner="dots", stream=sys.stderr)
    spinner.start()

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
        if reverse or generative:
            results = reversed(results)

        if generative:
            if reverse:
                click.echo("--reverse has no effect when using --generative", err=True)

            results = enhance_results(query, results, spinner, config)

        spinner.succeed()
        color_enabled = os.isatty(0) and not no_color and not vimgrep

        display_results(results, max_results, color_enabled, vimgrep)

        display_accuracy_warning(server_address)
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.RequestException,
        ServerDoesNotExist,
    ):
        spinner.fail()
        click.echo(
            f"The SeaGOAT server is not running. "
            f"Please start the server using the following command: "
            f"seagoat-server start {repo_path}",
            err=True,
        )
        sys.exit(ExitCode.SERVER_NOT_RUNNING)

    try:
        warn_if_update_available()
    except requests.exceptions.ConnectionError:
        click.echo(
            "Could not check for updates because the pypi.org API is not accessible",
            err=True,
        )


@click.command(name="orcarouter-login")
@click.option(
    "--api-key",
    is_flag=True,
    default=False,
    help="Paste an existing OrcaRouter API key instead of signing in.",
)
@click.option(
    "--flow",
    type=click.Choice(["oob", "loopback"]),
    default="oob",
    show_default=True,
    help=(
        "OAuth 2.0 + PKCE flow. 'oob' shows a code to paste back (works over "
        "SSH and in containers); 'loopback' listens on 127.0.0.1 and returns "
        "automatically."
    ),
)
@click.option(
    "--repo",
    "repo_path",
    default=os.getcwd(),
    help="Repository whose configuration to use.",
)
def orcarouter_login(api_key, flow, repo_path):
    """Connect SeaGOAT to OrcaRouter.

    Without options this starts the OAuth 2.0 + PKCE sign-in and stores the
    issued key. Use --api-key to paste a key you already have.
    """
    from seagoat.utils.orcarouter import (
        SOURCE_PKCE,
        ConnectError,
        connect,
        resolve_auth_base,
        write_record,
    )
    from seagoat.utils.orcarouter.credentials import looks_like_api_key

    config = get_config_values(Path(repo_path))
    generative_config = config.get("generative", {})

    if api_key:
        key = click.prompt("OrcaRouter API key", hide_input=True).strip()
        if not looks_like_api_key(key):
            click.echo(
                "That does not look like an OrcaRouter API key "
                "(expected it to start with 'sk-orca-').",
                err=True,
            )
            sys.exit(1)
        write_record({"api_key": key, "source": "api_key"})
        click.echo("OrcaRouter API key saved.")
        return

    try:
        payload = connect(
            resolve_auth_base(generative_config),
            "loopback" if flow == "loopback" else "oob",
            announce=lambda message: click.echo(message, err=True),
            prompt=lambda message: click.prompt(message.rstrip(": "), hide_input=True),
        )
    except ConnectError as error:
        click.echo(str(error), err=True)
        sys.exit(1)
    write_record(
        {
            "api_key": payload["key"],
            "source": SOURCE_PKCE,
            "scope": payload.get("scope"),
            "user_id": payload.get("user_id"),
        }
    )
    click.echo(
        f"Connected to OrcaRouter at {resolve_auth_base(generative_config)} "
        f"(scope: {payload.get('scope')}). The key is stored for reuse."
    )


@click.command(name="orcarouter-logout")
@click.option(
    "--repo",
    "repo_path",
    default=os.getcwd(),
    help="Repository whose configuration to use.",
)
def orcarouter_logout(repo_path):
    """Forget the stored OrcaRouter key.

    A key supplied through configuration or ORCAROUTER_API_KEY must be removed
    where it is defined; this command clears the key stored by the connect
    flow.
    """
    from seagoat.utils.orcarouter import clear_record, resolve_source_kind

    config = get_config_values(Path(repo_path))
    generative_config = config.get("generative", {})
    removed = clear_record()
    if removed:
        click.echo("The stored OrcaRouter key was removed.")
    else:
        click.echo("No stored OrcaRouter key to remove.")
    kind = resolve_source_kind(generative_config)
    if kind in ("api_key", "pkce"):
        click.echo(
            "Note: an OrcaRouter key is still resolvable from configuration or "
            "the ORCAROUTER_API_KEY environment variable.",
            err=True,
        )


@click.command(name="orcarouter-status")
@click.option(
    "--repo",
    "repo_path",
    default=os.getcwd(),
    help="Repository whose configuration to use.",
)
def orcarouter_status(repo_path):
    """Show how SeaGOAT is currently connected to OrcaRouter."""
    from seagoat.utils.orcarouter import (
        mask_secret,
        read_record,
        resolve_api_base,
        resolve_auth_base,
        resolve_api_key,
        resolve_source_kind,
    )

    config = get_config_values(Path(repo_path))
    generative_config = config.get("generative", {})
    key = resolve_api_key(generative_config)
    kind = resolve_source_kind(generative_config)
    record = read_record()

    click.echo(f"OrcaRouter status: {'connected' if key else 'not connected'}")
    if key:
        click.echo(f"  credential: {mask_secret(key)} (source: {kind})")
    if record.get("state"):
        click.echo(f"  key state:  {record['state']}")
    click.echo(f"  auth origin: {resolve_auth_base(generative_config)}")
    click.echo(f"  api origin:  {resolve_api_base(generative_config)}")
    click.echo("  key dashboard: https://www.orcarouter.ai/console/token")


@click.command(name="orcarouter-models")
@click.option(
    "--capability",
    type=click.Choice(["chat", "embedding", "image", "video", "rerank"]),
    default="chat",
    show_default=True,
    help="Capability to filter the catalog by.",
)
@click.option(
    "--modality",
    type=click.Choice(["text", "image", "audio", "video"]),
    default=None,
    help="Require text-chat models that declare this input modality.",
)
@click.option(
    "--repo",
    "repo_path",
    default=os.getcwd(),
    help="Repository whose configuration to use.",
)
def orcarouter_models(capability, modality, repo_path):
    """List OrcaRouter models compatible with a capability.

    The live catalog at <api origin>/models is authoritative; when it cannot
    be reached the verified offline catalog is used and reported as degraded.
    """
    from seagoat.utils.orcarouter import discover_models, public_options

    config = get_config_values(Path(repo_path))
    catalog = discover_models(config.get("generative", {}), capability=capability)
    if catalog.degraded:
        click.echo(
            f"Warning: live model discovery was unavailable ({catalog.error}); "
            f"showing the verified '{catalog.source}' catalog.",
            err=True,
        )
    options = public_options(catalog, capability, modality)
    for option in options:
        click.echo(option["id"])
    click.echo(
        f"{len(options)} model(s) available for capability '{capability}' "
        f"(source: {catalog.source}).",
        err=True,
    )


if __name__ == "__main__":
    seagoat()
