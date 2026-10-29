import json
import logging
import os
import sys
from collections import OrderedDict
from pathlib import Path

import click
import orjson
from flask import Flask, jsonify, request
from waitress import serve

from seagoat import __version__
from seagoat.cache import Cache, get_cache_root
from seagoat.projects import NotAGitRepo, Projects, UnknownProject
from seagoat.queue.task_queue import TaskQueue
from seagoat.utils.config import (
    GLOBAL_CONFIG_FILE,
    get_config_values,
    get_global_config_values,
)
from seagoat.utils.server import (
    ServerDoesNotExist,
    get_free_port,
    get_server_info,
    get_servers_info,
    is_git_repo,
    is_server_running,
    stop_server,
    update_server_info,
)
from seagoat.utils.wait import wait_for

logger = logging.getLogger(__name__)


class ExitCode:
    NOT_A_GIT_REPO = 5


class RepoPathRequired(Exception):
    pass


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _host_without_port(host: str) -> str:
    if host.startswith("["):
        return host[1 : host.find("]")]
    return host.rsplit(":", 1)[0]


def get_fallback_value(dictionary, key, fallback_value):
    if key not in dictionary or dictionary[key] is None:
        return fallback_value

    return dictionary[key]


def create_app(projects, host):
    logger.info("Creating server...")
    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = True
    app.debug = True

    app.extensions["projects"] = projects

    if host in LOOPBACK_HOSTS:

        @app.before_request
        def reject_requests_for_other_hosts():
            # Listening on a loopback address does not stop web pages from
            # reaching the server through DNS rebinding, but their requests
            # name the attacker's domain in the Host header
            if _host_without_port(request.host) not in LOOPBACK_HOSTS:
                return jsonify({"error": "Requests must be sent to localhost"}), 403
            return None

    def get_project_for_request():
        data = request.get_json(silent=True) or {}
        repo_path = data.get("repoPath")
        if repo_path is not None:
            # Requests only use projects the instance was configured with:
            # creating one runs git in the named directory, whose .git/config
            # can run commands.
            return projects.find(repo_path)

        loaded_paths = projects.repo_paths()
        if len(loaded_paths) == 1:
            return projects.find(loaded_paths[0])

        raise RepoPathRequired(
            f"repoPath required ({len(loaded_paths)} projects loaded)"
        )

    def execute_query(project, limit_clue, **kwargs) -> bytes:
        return project.queue.enqueue(
            "query",
            limit_clue=limit_clue,
            **kwargs,
        )

    @app.route("/lines/query", methods=["POST"])
    def query_lines():
        data = request.get_json(silent=True) or {}
        project = get_project_for_request()
        defaults = project.config["server"]["query"]
        query = get_fallback_value(data, "queryText", "")
        limit_clue = int(
            get_fallback_value(data, "limitClue", defaults["defaultLimitClue"])
        )
        context_above = int(
            get_fallback_value(data, "contextAbove", defaults["defaultContextAbove"])
        )
        context_below = int(
            get_fallback_value(data, "contextBelow", defaults["defaultContextBelow"])
        )

        return execute_query(
            project,
            query=query,
            context_above=context_above,
            context_below=context_below,
            limit_clue=limit_clue,
        )

    @app.route("/files/query", methods=["POST"])
    def query_files():
        data = request.get_json(silent=True) or {}
        project = get_project_for_request()
        defaults = project.config["server"]["query"]
        query = get_fallback_value(data, "queryText", "")
        limit_clue = int(
            get_fallback_value(data, "limitClue", defaults["defaultLimitClue"])
        )

        result = execute_query(
            project,
            query=query,
            context_above=0,
            context_below=0,
            limit_clue=limit_clue,
        )
        parsed_results = orjson.loads(result)
        files_dict = OrderedDict()

        for result_item in parsed_results["results"]:
            files_dict[result_item["fullPath"]] = {
                "path": result_item["path"],
                "fullPath": result_item["fullPath"],
            }

        return {**parsed_results, "results": list(files_dict.values())}

    @app.route("/status", methods=["GET"])
    def status_():
        return {
            "version": __version__,
            "pid": os.getpid(),
            "projects": projects.repo_paths(),
        }

    @app.route("/reload", methods=["POST"])
    def reload_():
        # Any caller may trigger this: it only reads the instance owner's config
        load_configured_projects(projects)
        return {"projects": projects.repo_paths()}

    @app.route("/status", methods=["POST"])
    def project_status():
        project = get_project_for_request()
        stats = project.queue.enqueue(
            "get_stats",
        )
        return {
            "stats": stats,
            "version": __version__,
        }

    @app.errorhandler(NotAGitRepo)
    @app.errorhandler(UnknownProject)
    @app.errorhandler(RepoPathRequired)
    def handle_project_errors(exception_to_handle):
        if isinstance(exception_to_handle, UnknownProject):
            code = 404
        else:
            code = 400

        res = {
            "code": code,
            "error": {
                "type": type(exception_to_handle).__name__,
                "message": str(exception_to_handle),
            },
        }

        return jsonify(res), code

    @app.errorhandler(Exception)
    def handle_exception(exception_to_handle):
        res = {
            "code": 500,
            "error": {
                "type": "Internal Server Error",
                "message": exception_to_handle.message
                if hasattr(exception_to_handle, "message")
                else f"{exception_to_handle}",
            },
        }

        return jsonify(res), 500

    return app


def load_configured_projects(projects) -> None:
    for configured_path in get_global_config_values()["server"]["repositories"]:
        try:
            projects.get(configured_path)
        except NotAGitRepo as error:
            logger.warning(
                "Skipping configured repository %s: %r", configured_path, error
            )


def start_server(repo_path: str, custom_port=None):
    if not is_git_repo(repo_path):
        click.echo(
            f"SeaGOAT can only operate in Git repositories. No Git repository found at path '{repo_path}'.",
            err=True,
        )
        sys.exit(ExitCode.NOT_A_GIT_REPO)

    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    projects = Projects(
        lambda path, config: TaskQueue(repo_path=path, minimum_chunks_to_analyze=0)
    )
    load_configured_projects(projects)
    projects.get(repo_path)
    port = custom_port

    if port is None:
        port = get_free_port()

    update_server_info(
        repo_path,
        {
            "host": "localhost",
            "port": port,
            "address": f"http://localhost:{port}",
            "pid": os.getpid(),
        },
    )
    host = get_config_values(Path(repo_path))["server"]["host"]
    app = create_app(projects, host)
    serve(app, host=host, port=port, threads=4)


def get_server(repo_path, custom_port=None):
    port = None
    try:
        server_info = get_server_info(repo_path)
        server_address = server_info["address"]

        if is_server_running(repo_path):
            click.echo(f"Server is already running at {server_address}")
            return server_address
    except ServerDoesNotExist:
        pass

    if custom_port is not None:
        port = custom_port

    os.environ["TOKENIZERS_PARALLELISM"] = "true"

    start_server(str(repo_path), custom_port=port)

    wait_for(lambda: get_server_info(repo_path), timeout=60)

    server_info = get_server_info(repo_path)
    click.echo(f"Server started at {server_info['address']}")
    return server_info["address"]


@click.group()
@click.version_option(version=__version__, prog_name="seagoat")
def server():
    """
    This server analyzes your codebase and creates vector embeddings for it.

    You can query this server using the seagoat command.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


@server.command()
@click.argument("repo_path")
@click.option("--port", type=int, help="The port to start the server on", default=None)
def start(repo_path, port):
    """Starts the server."""
    config = get_config_values(Path(repo_path))
    port = port if port is not None else config["server"]["port"]

    get_server(repo_path, custom_port=port)
    click.echo("Server running.")


def get_status_data(repo_path):
    """Return the status data of the server."""
    status_info = {"isRunning": False, "url": None, "pid": None}

    try:
        server_info = get_server_info(repo_path)
        server_address = server_info["address"]
        pid = server_info.get("pid", None)

        if is_server_running(repo_path):
            status_info = {
                "isRunning": True,
                "url": server_address,
                "pid": pid,
            }

    except ServerDoesNotExist:
        pass

    return status_info


@server.command()
@click.argument("repo_path")
@click.option("--json", "use_json_format", is_flag=True, help="Output status as JSON.")
def status(repo_path, use_json_format):
    """Checks the status of the server."""
    status_info = get_status_data(repo_path)

    if use_json_format:
        click.echo(json.dumps(status_info))
    else:
        if status_info["isRunning"]:
            click.echo(f"Server is running at {status_info['url']}")
        else:
            click.echo("Server is not running.")


@server.command()
@click.argument("repo_path")
def stop(repo_path):
    """Stops the server."""
    try:
        stop_server(repo_path)
    except ServerDoesNotExist:
        click.echo(
            f"No server information found for {repo_path}. It might not be running or was never started."
        )
        return

    click.echo(
        "Server stopped. If it was running, it will stop after finishing current tasks."
    )


@server.command(name="server-info")
def _server_info():
    """Returns information about all SeaGOAT servers in JSON format."""
    servers_info = get_servers_info()
    formatted_servers_info = {}

    for normalized_repo_path, info in servers_info.items():
        formatted_servers_info[normalized_repo_path] = {
            "repoPath": normalized_repo_path,
            "cacheLocation": {
                "chroma": str(
                    Cache("chroma", Path(normalized_repo_path), {}).get_cache_folder(),
                ),
                "ripgrep": str(
                    Cache("ripgrep", Path(normalized_repo_path), {}).get_cache_folder(),
                ),
            },
            "isRunning": is_server_running(normalized_repo_path),
            "host": info["host"],
            "port": info["port"],
            "address": f"http://{info['host']}:{info['port']}",
        }

    info = {
        "version": __version__,
        "servers": formatted_servers_info,
        "globalCache": str(get_cache_root()),
        "globalConfigFile": str(GLOBAL_CONFIG_FILE),
    }

    click.echo(json.dumps(info))


if __name__ == "__main__":
    server()
