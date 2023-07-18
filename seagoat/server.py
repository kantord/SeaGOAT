import json
import os
import socket
import time
from multiprocessing import Process

import appdirs
import click
import pkg_resources
from flask import current_app
from flask import Flask
from flask import jsonify
from werkzeug.serving import run_simple

from seagoat.engine import Engine


def create_app(repo_path):
    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = True

    seagoat_engine = Engine(repo_path)
    seagoat_engine.analyze_codebase()
    app.extensions["seagoat_engine"] = seagoat_engine

    @app.route("/query/<query>")
    def query_codebase(query):
        if "seagoat_engine" not in current_app.extensions:
            raise RuntimeError("seagoat_engine is not initialized")
        current_app.extensions["seagoat_engine"].query(query)
        current_app.extensions["seagoat_engine"].fetch_sync()
        results = current_app.extensions["seagoat_engine"].get_results()
        return {
            "results": [result.to_json() for result in results],
            "version": pkg_resources.get_distribution("seagoat").version,
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


def start_server(repo_path):
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    socket_obj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_obj.bind(("", 0))
    _, port = socket_obj.getsockname()
    socket_obj.close()

    server_info_file = get_server_info_file(repo_path)
    with open(server_info_file, "w", encoding="utf-8") as file:
        json.dump({"host": "localhost", "port": port}, file)

    app = create_app(repo_path)
    process = Process(
        target=run_simple, args=("localhost", port, app), kwargs={"use_reloader": False}
    )
    process.start()


def is_server_running(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_obj:
        return socket_obj.connect_ex((host, port)) == 0


def load_server_info(server_info_file):
    with open(server_info_file, "r", encoding="utf-8") as file:
        server_info = json.load(file)
    host = server_info["host"]
    port = server_info["port"]
    server_address = f"http://{host}:{port}"
    return host, port, server_address


def wait_for(condition_function, timeout, period=0.05):
    start_time = time.time()
    while not condition_function():
        if time.time() - start_time > timeout:
            raise TimeoutError("Timeout expired while waiting for condition.")
        time.sleep(period)


def get_server(repo_path):
    server_info_file = get_server_info_file(repo_path)

    if os.path.exists(server_info_file):
        host, port, server_address = load_server_info(server_info_file)

        if is_server_running(host, port):
            click.echo(f"Server is already running at {server_address}")
            return server_address
        os.remove(server_info_file)

    # Pre-create app in order to give the user feedback on creating
    # the initial database
    os.environ["TOKENIZERS_PARALLELISM"] = "true"
    temp_app = create_app(repo_path)
    del temp_app

    start_server(str(repo_path))

    wait_for(lambda: os.path.exists(server_info_file), timeout=60)

    host, port, server_address = load_server_info(server_info_file)
    click.echo(f"Server started at {server_address}")
    return server_address


@click.group()
def server():
    pass


@server.command()
@click.argument("repo_path")
def start(repo_path):
    """Starts the server."""
    get_server(repo_path)
    click.echo("Server running.")


@server.command()
@click.argument("repo_path")
def status(repo_path):
    """Checks the status of the server."""
    server_info_file = get_server_info_file(repo_path)

    if os.path.exists(server_info_file):
        with open(server_info_file, "r", encoding="utf-8") as file:
            server_info = json.load(file)

        host = server_info["host"]
        port = server_info["port"]
        server_address = f"http://{host}:{port}"

        if is_server_running(host, port):
            click.echo(f"Server is running at {server_address}")
        else:
            click.echo("Server is not running.")
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
