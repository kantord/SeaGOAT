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
from seagoat.cache import Cache
from seagoat.projects import (
    NotAGitRepo,
    Projects,
    UnknownProject,
    find_repositories_in_directory,
    git_root,
    resolve_repo_path,
)
from seagoat.queue.base_queue import TaskTimedOut
from seagoat.queue.task_queue import TaskQueue
from seagoat.utils.config import (
    GLOBAL_CONFIG_FILE,
    get_global_config_values,
)
from seagoat.utils.paths import get_cache_dir
from seagoat.utils.server import (
    Instance,
    add_repository,
    claim_start,
    client_host,
    instance_url,
    normalize_repo_path,
    read_repositories,
    repositories_file_path,
    running_instance,
    stop_instance,
)

logger = logging.getLogger(__name__)


class ExitCode:
    NOT_A_GIT_REPO = 5
    BIND_FAILED = 6
    SERVER_ERROR = 4


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
        failed = load_configured_projects(projects)
        return {"projects": projects.repo_paths(), "failed": failed}

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

    @app.errorhandler(UnknownProject)
    @app.errorhandler(RepoPathRequired)
    def handle_project_errors(exception_to_handle):
        if isinstance(exception_to_handle, UnknownProject):
            code = 404
            repo_path = str(exception_to_handle)
            message = (
                f"The SeaGOAT server does not serve the repository at {repo_path!r}. "
                f"Run `seagoat-server start {repo_path}` to add it to the server."
            )
        else:
            code = 400
            message = str(exception_to_handle)

        res = {
            "code": code,
            "error": {
                "type": type(exception_to_handle).__name__,
                "message": message,
            },
        }

        return jsonify(res), code

    @app.errorhandler(TaskTimedOut)
    def handle_task_timed_out(exception_to_handle):
        code = 503
        project = get_project_for_request()
        message = f"{project.repo_path} is busy (indexing); try again shortly"
        res = {
            "code": code,
            "error": {
                "type": type(exception_to_handle).__name__,
                "message": message,
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


def load_configured_projects(projects) -> dict[str, str]:
    """Load every listed repository; return the ones that failed, path -> error."""
    failed = {}
    for configured_path in read_repositories():
        try:
            projects.get(configured_path)
        except Exception as error:  # noqa: BLE001 - deliberately skip any bad repository
            # One bad repository must not take the whole instance down: log
            # which path failed and why, and keep loading the rest.
            logger.warning(
                "Skipping configured repository %s: %r", configured_path, error
            )
            failed[configured_path] = str(error)
    return failed


class RepositoryFileWriteError(Exception):
    pass


class RepositoryLoadError(Exception):
    def __init__(self, repo_path: str, reason: str):
        super().__init__(reason)
        self.repo_path = repo_path
        self.reason = reason


def find_repositories_to_serve(repo_path: str) -> tuple[list[str], bool]:
    """Return the repositories that ``start repo_path`` should serve, and whether
    they were found inside a directory (rather than repo_path itself being a
    repository).

    When repo_path is a repository root it is served as-is. Otherwise each of its
    direct subdirectories that is itself a repository root is served, in the same
    start (no deeper search and no children picked up later without re-running
    ``start``). This also holds for a folder of repositories that sits inside
    another work tree (say ~/repos inside a dotfiles repository at ~). A
    subdirectory of a repository with no repositories in it serves that
    repository. Anything else exits with the usual error.
    """
    try:
        root = git_root(repo_path)
    except NotAGitRepo:
        root = None
    if root is not None and normalize_repo_path(root) == normalize_repo_path(repo_path):
        return [repo_path], False
    repositories = find_repositories_in_directory(repo_path)
    if repositories:
        return repositories, True
    if root is not None:
        return [repo_path], False
    click.echo(
        f"SeaGOAT can only operate in Git repositories. No Git repository found at path '{repo_path}'.",
        err=True,
    )
    sys.exit(ExitCode.NOT_A_GIT_REPO)


def start_server(repo_path: str, custom_port=None):
    repositories, found_in_directory = find_repositories_to_serve(repo_path)

    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    config = get_global_config_values()
    host = config["server"]["host"]
    port = custom_port if custom_port is not None else config["server"]["port"]
    if port is None:
        port = 0

    server = None
    load_failures: list[str] = []
    repo_roots = [normalize_repo_path(resolve_repo_path(path)) for path in repositories]

    def bind() -> Instance:
        nonlocal server
        projects = Projects(lambda path, config: TaskQueue(repo_path=path))
        app = create_app(projects, host)
        server = create_server(app, host=host, port=port, threads=16)
        # Bind the port before loading any project: loading runs git in the
        # listed repositories, and a repository that fails to load must not
        # leave the instance file behind a bound-but-unusable socket.
        try:
            failed = load_configured_projects(projects)
        except Exception:
            server.close()
            raise
        # One bad repository in a folder of them must not block the others:
        # fail only when nothing that was asked for loaded.
        failed_roots = [root for root in repo_roots if root in failed]
        if len(failed_roots) == len(repo_roots):
            server.close()
            raise RepositoryLoadError(failed_roots[0], failed[failed_roots[0]])
        load_failures.extend(failed_roots)
        for root in failed_roots:
            click.echo(f"Warning: could not load {root}: {failed[root]}", err=True)
        return Instance(host, int(server.effective_port), os.getpid())  # type: ignore  # set in waitress at runtime

    def prepare() -> None:
        try:
            for repository in repositories:
                add_repository(repository)
        except OSError as error:
            raise RepositoryFileWriteError(
                f"could not write {repositories_file_path()}: {error}"
            ) from error

    try:
        existing = claim_start(bind, prepare=prepare)
    except RepositoryFileWriteError as error:
        click.echo(f"Error: {error}", err=True)
        sys.exit(ExitCode.SERVER_ERROR)
    except RepositoryLoadError as error:
        click.echo(f"Could not load {error.repo_path}: {error.reason}", err=True)
        sys.exit(ExitCode.SERVER_ERROR)
    except OSError as error:
        click.echo(
            f"Error: could not bind to {host}:{port} - {error.strerror or error}",
            err=True,
        )
        sys.exit(ExitCode.BIND_FAILED)

    if existing is not None:
        address = instance_url(existing)
        if custom_port is not None and custom_port != existing.port:
            click.echo(
                f"Warning: --port {custom_port} ignored; the running instance keeps port {existing.port}",
                err=True,
            )
        try:
            running = running_instance()
            previously_served = set(running[1].get("projects", []) if running else [])
            response = requests.post(f"{address}/reload", timeout=5)
            response.raise_for_status()
            reloaded = response.json()
            projects = reloaded.get("projects") or []
            failed = reloaded.get("failed") or {}
        except (requests.exceptions.RequestException, ValueError) as error:
            click.echo(
                f"Error: could not reload the running instance at {address} - {error}",
                err=True,
            )
            sys.exit(ExitCode.SERVER_ERROR)
        missing = [root for root in repo_roots if root not in projects]
        for root in missing:
            reason = failed.get(root, "see the instance's log")
            prefix = (
                "Could not load"
                if len(missing) == len(repo_roots)
                else "Warning: could not load"
            )
            click.echo(f"{prefix} {root}: {reason}", err=True)
        if len(missing) == len(repo_roots):
            sys.exit(ExitCode.SERVER_ERROR)
        repo_roots = [root for root in repo_roots if root not in missing]
        newly_served = [root for root in repo_roots if root not in previously_served]
        if len(repo_roots) == 1:
            if newly_served:
                click.echo(f"Repository added to the running instance at {address}")
            else:
                click.echo(
                    f"{repo_roots[0]} is already served by the instance at {address}"
                )
        elif newly_served:
            click.echo(f"Added repositories to the running instance at {address}:")
            for root in newly_served:
                click.echo(f"  {root}")
        else:
            click.echo(
                f"All {len(repo_roots)} repositories are already served by the instance at {address}"
            )
        return

    if server is None:
        # claim_start returned None, so bind() ran and created the server
        raise RuntimeError("start_server: bind() did not create a server")
    if found_in_directory:
        click.echo("Added repositories:")
        for root in repo_roots:
            if root not in load_failures:
                click.echo(f"  {root}")
    listening = Instance(client_host(host), int(server.effective_port), os.getpid())  # type: ignore  # set in waitress at runtime
    click.echo(f"Instance listening at {instance_url(listening)}")
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
    """Adds REPO_PATH to the instance and serves it.

    REPO_PATH is a Git repository, or a folder whose direct subfolders are Git
    repositories. Without a running instance, this starts one and keeps
    running in the foreground; with one, it adds the repository to it and
    returns at once. The served repositories are kept in repositories.json.
    """
    start_server(repo_path, custom_port=port)


def get_status_data(repo_path=None):
    """Return the status data of the instance; with repo_path, whether it serves that repo."""
    status_info = {"isRunning": False, "url": None, "pid": None, "projects": []}

    running = running_instance()
    if running is None:
        return status_info

    instance, status = running
    projects = status.get("projects") or []
    if (
        repo_path is not None
        and normalize_repo_path(resolve_repo_path(repo_path)) not in projects
    ):
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
    if use_json_format:
        click.echo(json.dumps(get_status_data(repo_path)))
        return

    status_info = get_status_data()
    if not status_info["isRunning"]:
        click.echo("No SeaGOAT instance running.")
    elif repo_path is not None and (
        normalize_repo_path(resolve_repo_path(repo_path)) not in status_info["projects"]
    ):
        click.echo(
            f"The instance at {status_info['url']} does not serve {normalize_repo_path(resolve_repo_path(repo_path))}."
        )
    else:
        click.echo(f"Instance is running at {status_info['url']}")


@server.command()
@click.argument("repo_path", required=False)
def stop(repo_path):
    """Stops the instance, for every repository it serves.

    A REPO_PATH argument is accepted for compatibility and ignored.
    """
    if repo_path is not None:
        click.echo(
            "Note: stop stops the whole instance, for every repository it serves.",
            err=True,
        )
    outcome, pid = stop_instance()
    if outcome == "stopped":
        click.echo("Instance stopped.")
    elif outcome == "not_running":
        click.echo("No SeaGOAT instance running.")
    else:
        click.echo(
            f"Could not verify that pid {pid} is SeaGOAT; not stopped.",
            err=True,
        )
        sys.exit(1)


@server.command(name="server-info")
def _server_info():
    """Returns information about the repositories served by the SeaGOAT instance in JSON format."""
    formatted_servers_info = {}

    running = running_instance()
    if running is not None:
        instance, status = running
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
        "globalCache": str(get_cache_dir()),
        "globalConfigFile": str(GLOBAL_CONFIG_FILE),
    }

    click.echo(json.dumps(info))


if __name__ == "__main__":
    server()
