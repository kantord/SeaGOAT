import json
import logging
import os

import click
from flask import current_app
from flask import Flask
from flask import jsonify
from flask import request
from waitress import serve

from seagoat import __version__
from seagoat.queue.task_queue import TaskQueue
from seagoat.utils.server import get_free_port
from seagoat.utils.server import get_server_info
from seagoat.utils.server import is_server_running
from seagoat.utils.server import remove_server_info
from seagoat.utils.server import ServerDoesNotExist
from seagoat.utils.server import update_server_info
from seagoat.utils.wait import wait_for


def create_app(repo_path):
    logging.info("Creating server...")
    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = True

    app.extensions["task_queue"] = TaskQueue(
        repo_path=repo_path, minimum_chunks_to_analyze=0
    )

    @app.route("/query/<query>")
    def query_codebase(query):
        limit_clue = request.args.get("limitClue", "500")
        context_above = request.args.get("contextAbove", 0)
        context_below = request.args.get("contextBelow", 0)

        try:
            limit_clue = int(limit_clue)
        except ValueError as exception:
            raise RuntimeError(
                "Invalid limitClue value. Must be an integer."
            ) from exception

        result = current_app.extensions["task_queue"].enqueue(
            "query",
            query=query,
            context_below=int(context_below),
            context_above=int(context_above),
            limit_clue=limit_clue,
        )

        return result

    @app.route("/status")
    def status_():
        stats = current_app.extensions["task_queue"].enqueue(
            "get_stats",
        )
        return {
            "stats": stats,
            "version": __version__,
        }

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


def start_server(repo_path, custom_port=None):
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    app = create_app(repo_path)
    port = custom_port

    if port is None:
        port = get_free_port()

    new_server_data = {"host": "localhost", "port": port, "pid": os.getpid()}
    update_server_info(repo_path, new_server_data)
    serve(app, host="0.0.0.0", port=port, threads=1)


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
            status_info = {"isRunning": True, "url": server_address, "pid": pid}

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
        remove_server_info(repo_path)
    except ServerDoesNotExist:
        click.echo(
            f"No server information found for {repo_path}. It might not be running or was never started."
        )
        return

    click.echo(
        "Server stopped. If it was running, it will stop after finishing current tasks."
    )


if __name__ == "__main__":
    server()
