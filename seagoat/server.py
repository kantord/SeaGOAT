import json
import os
import socket
import time
from multiprocessing import Process

import appdirs
import click
from flask import current_app
from flask import Flask
from flask import jsonify
from flask import request
from werkzeug.serving import run_simple

from seagoat import __version__
from seagoat.queue import TaskQueue


def create_app(repo_path):
    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = True

    app.extensions["task_queue"] = TaskQueue(repo_path)

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

        results = current_app.extensions["task_queue"].enqueue(
            "query",
            query=query,
            context_below=int(context_below),
            context_above=int(context_above),
            limit_clue=limit_clue,
        )

        for result in results:
            if context_above:
                result.add_context_lines(-int(context_above))

        return {
            "results": [result.to_json(query) for result in results],
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


def get_server_info_file(repo_path):
    repo_id = os.path.normpath(repo_path).replace(os.sep, "_")
    user_cache_dir = appdirs.user_cache_dir("seagoat-servers")
    os.makedirs(user_cache_dir, exist_ok=True)
    return os.path.join(user_cache_dir, f"{repo_id}.json")


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


def load_server_info(server_info_file):
    with open(server_info_file, "r", encoding="utf-8") as file:
        server_info = json.load(file)
    host = server_info["host"]
    port = server_info["port"]
    pid = server_info.get("pid")
    server_address = f"http://{host}:{port}"
    return host, port, pid, server_address


def wait_for(condition_function, timeout, period=0.05):
    start_time = time.time()
    while not condition_function():
        if time.time() - start_time > timeout:
            raise TimeoutError("Timeout expired while waiting for condition.")
        time.sleep(period)


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
    temp_app = create_app(repo_path)
    temp_app.extensions["task_queue"].shutdown()
    del temp_app

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
        with open(server_info_file, "r", encoding="utf-8") as file:
            server_info = json.load(file)

        host = server_info["host"]
        port = server_info["port"]
        pid = server_info.get("pid")
        server_address = f"http://{host}:{port}"

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
