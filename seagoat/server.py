import json
import os
import socket

import appdirs
import click
from flask import current_app
from flask import Flask
from werkzeug.serving import run_simple

from seagoat.engine import Engine


def startup_event():
    if "seagoat_engine" not in current_app.extensions:
        raise RuntimeError("seagoat_engine is not initialized")
    current_app.extensions["seagoat_engine"].analyze_codebase()


def create_app(repo_path):
    app = Flask(__name__)

    seagoat_engine = Engine(repo_path)
    app.extensions["seagoat_engine"] = seagoat_engine

    @app.route("/query/<query>")
    def query_codebase(query):
        if "seagoat_engine" not in current_app.extensions:
            raise RuntimeError("seagoat_engine is not initialized")
        current_app.extensions["seagoat_engine"].query(query)
        current_app.extensions["seagoat_engine"].fetch_sync()
        results = current_app.extensions["seagoat_engine"].get_results()
        return {"results": [result.to_json() for result in results]}

    with app.app_context():
        startup_event()

    return app


def get_server_info_file(repo_path):
    repo_id = os.path.normpath(repo_path).replace(os.sep, "_")
    user_cache_dir = appdirs.user_cache_dir("seagoat-servers")
    os.makedirs(user_cache_dir, exist_ok=True)
    return os.path.join(user_cache_dir, f"{repo_id}.json")


def start_server(repo_path):
    app = create_app(repo_path)

    socket_obj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_obj.bind(("", 0))
    _, port = socket_obj.getsockname()
    socket_obj.close()

    server_info_file = get_server_info_file(repo_path)
    with open(server_info_file, "w", encoding="utf-8") as file:
        json.dump({"host": "localhost", "port": port}, file)

    run_simple("localhost", port, app)


def is_server_running(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_obj:
        return socket_obj.connect_ex((host, port)) == 0


def get_server(repo_path):
    server_info_file = get_server_info_file(repo_path)

    if os.path.exists(server_info_file):
        with open(server_info_file, "r", encoding="utf-8") as file:
            server_info = json.load(file)

        host = server_info["host"]
        port = server_info["port"]
        server_address = f"http://{host}:{port}"

        if is_server_running(host, port):
            return server_address
        os.remove(server_info_file)

    start_server(repo_path)
    return get_server(repo_path)


@click.group()
def cli():
    pass


@cli.command()
@click.argument("repo_path")
def start(repo_path):
    """Starts the server."""
    get_server(repo_path)
    click.echo("Server running.")


@cli.command()
@click.argument("repo_path")
def status(repo_path):
    """Checks the status of the server."""
    server_info_file = get_server_info_file(repo_path)

    if os.path.exists(server_info_file):
        with open(server_info_file, "r", encoding="utf-8") as file:
            server_info = json.load(file)

        host = server_info["host"]
        port = server_info["port"]

        if is_server_running(host, port):
            click.echo("Server is running.")
        else:
            click.echo("Server is not running.")
    else:
        click.echo("Server is not running.")


@cli.command()
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
    cli()
