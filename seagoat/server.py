import json
import logging
import os
import socket
from multiprocessing import Process

import click
from flask import current_app
from flask import Flask
from flask import jsonify
from flask import request
from werkzeug.serving import run_simple

from seagoat import __version__
from seagoat.queue.task_queue import TaskQueue
from seagoat.utils.server import get_server_info_file
from seagoat.utils.server import load_server_info
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

        result = current_app.extensions["task_queue"].enqueue_high_prio(
            "query",
            query=query,
            context_below=int(context_below),
            context_above=int(context_above),
            limit_clue=limit_clue,
        )

        return result

    @app.route("/status")
    def status_():
        stats = current_app.extensions["task_queue"].enqueue_high_prio(
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


def get_free_port():
    socket_obj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_obj.bind(("", 0))
    _, port = socket_obj.getsockname()
    socket_obj.close()

    return port


def start_server(repo_path, custom_port=None):
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    app = create_app(repo_path)
    port = custom_port

    if port is None:
        port = get_free_port()

    process = Process(
        target=run_simple, args=("localhost", port, app), kwargs={"use_reloader": False}
    )
    process.start()

    server_info_file = get_server_info_file(repo_path)
    with open(server_info_file, "w", encoding="utf-8") as file:
        json.dump({"host": "localhost", "port": port, "pid": process.pid}, file)


def is_server_running(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_obj:
        return socket_obj.connect_ex((host, port)) == 0


def get_server(repo_path, custom_port=None):
    server_info_file = get_server_info_file(repo_path)
    port = None

    if os.path.exists(server_info_file):
        host, port, _, server_address = load_server_info(server_info_file)

        if is_server_running(host, port):
            click.echo(f"Server is already running at {server_address}")
            return server_address
        os.remove(server_info_file)

    if custom_port is not None:
        port = custom_port

    os.environ["TOKENIZERS_PARALLELISM"] = "true"

    start_server(str(repo_path), custom_port=port)

    wait_for(lambda: os.path.exists(server_info_file), timeout=60)

    host, port, _, server_address = load_server_info(server_info_file)
    click.echo(f"Server started at {server_address}")
    return server_address


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
    server_info_file = get_server_info_file(repo_path)
    status_info = {"isRunning": False, "url": None}

    if os.path.exists(server_info_file):
        host, port, pid, server_address = load_server_info(server_info_file)

        if is_server_running(host, port):
            status_info = {"isRunning": True, "url": server_address, "pid": pid}

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
    server_info_file = get_server_info_file(repo_path)

    if os.path.exists(server_info_file):
        os.remove(server_info_file)

    click.echo(
        "Server stopped. If it was running, it will stop after finishing current tasks."
    )


if __name__ == "__main__":
    server()
