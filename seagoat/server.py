import json
import logging
import os
import sys
from collections import OrderedDict
from pathlib import Path

import click
import orjson
import requests
from flask import Flask, jsonify, request
from waitress.server import create_server

from seagoat import __version__
from seagoat.cache import Cache, get_cache_root
from seagoat.projects import NotAGitRepo, Projects, UnknownProject
from seagoat.queue.task_queue import TaskQueue
from seagoat.utils.config import (
    GLOBAL_CONFIG_FILE,
    add_repository,
    get_global_config_values,
)
from seagoat.utils.server import (
    Instance,
    claim_start,
    fetch_status,
    instance_url,
    is_git_repo,
    normalize_repo_path,
    read_instance,
    stop_instance,
)

logger = logging.getLogger(__name__)


class ExitCode:
    NOT_A_GIT_REPO = 5
    BIND_FAILED = 6


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
    config = get_global_config_values()
    host = config["server"]["host"]
    port = custom_port if custom_port is not None else config["server"]["port"]
    if port is None:
        port = 0

    server = None

    def bind() -> Instance:
        nonlocal server
        projects = Projects(
            lambda path, config: TaskQueue(repo_path=path, minimum_chunks_to_analyze=0)
        )
        load_configured_projects(projects)
        projects.get(repo_path)
        app = create_app(projects, host)
        server = create_server(app, host=host, port=port, threads=4)
        return Instance(host, int(server.effective_port), os.getpid())  # type: ignore  # set in waitress at runtime

    def prepare() -> None:
        add_repository(repo_path)

    try:
        existing = claim_start(bind, prepare=prepare)
    except OSError as error:
        click.echo(
            f"Error: could not bind to {host}:{port} - {error.strerror or error}",
            err=True,
        )
        sys.exit(ExitCode.BIND_FAILED)

    if existing is not None:
        address = instance_url(existing)
        requests.post(f"{address}/reload", timeout=5)
        click.echo(f"Repository added to the running instance at {address}")
        return

    assert server is not None  # claim_start returned None, so bind() ran
    listen_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    click.echo(f"Instance listening at http://{listen_host}:{server.effective_port}")
    server.run()


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
    start_server(repo_path, custom_port=port)


def get_status_data(repo_path=None):
    """Return the status data of the instance; with repo_path, whether it serves that repo."""
    status_info = {"isRunning": False, "url": None, "pid": None, "projects": []}

    instance = read_instance()
    if instance is None:
        return status_info

    status = fetch_status(instance)
    if status is None or status.get("pid") != instance.pid:
        return status_info

    projects = status.get("projects") or []
    if repo_path is not None and normalize_repo_path(repo_path) not in projects:
        return status_info

    return {
        "isRunning": True,
        "url": instance_url(instance),
        "pid": status.get("pid"),
        "projects": projects,
    }


@server.command()
@click.argument("repo_path", required=False)
@click.option("--json", "use_json_format", is_flag=True, help="Output status as JSON.")
def status(repo_path, use_json_format):
    """Describes the SeaGOAT instance; with REPO_PATH, whether it serves that repo."""
    status_info = get_status_data(repo_path)

    if use_json_format:
        click.echo(json.dumps(status_info))
    else:
        if status_info["isRunning"]:
            click.echo(f"Instance is running at {status_info['url']}")
        else:
            click.echo("No SeaGOAT instance running.")


@server.command()
def stop():
    """Stops the instance."""
    if stop_instance():
        click.echo("Instance stopped.")
    else:
        click.echo("No SeaGOAT instance running")


@server.command(name="server-info")
def _server_info():
    """Returns information about all SeaGOAT servers in JSON format."""
    formatted_servers_info = {}

    instance = read_instance()
    if instance is not None:
        status = fetch_status(instance)
        if status is not None and status.get("pid") == instance.pid:
            for repo_path in status.get("projects") or []:
                formatted_servers_info[repo_path] = {
                    "repoPath": repo_path,
                    "cacheLocation": {
                        "chroma": str(
                            Cache("chroma", Path(repo_path), {}).get_cache_folder(),
                        ),
                        "ripgrep": str(
                            Cache("ripgrep", Path(repo_path), {}).get_cache_folder(),
                        ),
                    },
                    "isRunning": True,
                    "host": instance.host,
                    "port": instance.port,
                    "address": instance_url(instance),
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
