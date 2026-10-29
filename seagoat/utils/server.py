import os
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, TypedDict

import platformdirs
import psutil
import requests
from filelock import FileLock

from seagoat.utils.json_file import get_json_file_contents, write_to_json_file


class ServerInfo(TypedDict):
    address: str
    host: str
    port: int
    pid: int


class ServerDoesNotExist(Exception):
    pass


def _get_server_data_file_path() -> Path:
    user_cache_dir = Path(
        platformdirs.user_cache_dir(
            "seagoat-servers-pytest"
            if "PYTEST_CURRENT_TEST" in os.environ
            else "seagoat-servers"
        )
    )
    user_cache_dir.mkdir(parents=True, exist_ok=True)
    return user_cache_dir / "serverData.json"


def normalize_repo_path(repo_path: str | Path) -> str:
    return str(
        os.path.normcase(os.path.normpath(Path(repo_path).expanduser().resolve()))
    )


def get_servers_info() -> dict[str, ServerInfo]:
    path = _get_server_data_file_path()
    if not os.path.exists(path):
        write_to_json_file(path, {})

    contents = get_json_file_contents(path)
    if contents is None:
        contents = {}

    for key in list(contents.keys()):
        if not os.path.exists(key):
            del contents[key]

    return contents


def update_server_info(repo_path: str | Path, new_server_data: ServerInfo) -> None:
    servers_info = get_servers_info()
    repo_id = normalize_repo_path(repo_path)
    servers_info[repo_id] = new_server_data

    write_to_json_file(_get_server_data_file_path(), servers_info)


def stop_server(repo_path: str | Path) -> None:
    servers_info = get_servers_info()
    repo_id = normalize_repo_path(repo_path)
    if repo_id in servers_info:
        server_info = servers_info[repo_id]
        process = psutil.Process(server_info["pid"])

        servers_info.pop(repo_id)
        write_to_json_file(_get_server_data_file_path(), servers_info)

        process.terminate()
        process.wait()
    else:
        raise ServerDoesNotExist(f"Server for {repo_path} does not exist.")


def get_server_info(repo_path: str | Path) -> ServerInfo:
    servers_info = get_servers_info()
    repo_id = normalize_repo_path(repo_path)

    if repo_id not in servers_info:
        raise ServerDoesNotExist(f"Server for {repo_path} does not exist.")

    server_info = servers_info[repo_id]
    return server_info


def is_server_running(repo_path: str | Path) -> bool:
    try:
        server_info = get_server_info(repo_path)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_obj:
            return (
                socket_obj.connect_ex((server_info["host"], server_info["port"])) == 0
            )
    except ServerDoesNotExist:
        return False


def get_free_port() -> int:
    socket_obj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_obj.bind(("", 0))
    _, port = socket_obj.getsockname()
    socket_obj.close()

    return port


def is_git_repo(path: str) -> bool:
    try:
        output = subprocess.check_output(
            ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return output.strip().lower() == "true"
    except subprocess.CalledProcessError:
        return False


class Instance(NamedTuple):
    host: str  # the address clients use
    port: int
    pid: int


def instance_file_path() -> Path:
    user_cache_dir = Path(
        platformdirs.user_cache_dir(
            "seagoat-servers-pytest"
            if "PYTEST_CURRENT_TEST" in os.environ
            else "seagoat-servers"
        )
    )
    user_cache_dir.mkdir(parents=True, exist_ok=True)
    return user_cache_dir / "instance.json"


def write_instance(instance: Instance) -> None:
    host = {
        "0.0.0.0": "127.0.0.1",
        "::": "::1",
    }.get(instance.host, instance.host)

    write_to_json_file(
        instance_file_path(),
        {"host": host, "port": instance.port, "pid": instance.pid},
    )


def read_instance() -> Instance | None:
    try:
        contents = get_json_file_contents(instance_file_path())
    except (OSError, ValueError):
        return None

    if not isinstance(contents, dict):
        return None

    host = contents.get("host")
    port = contents.get("port")
    pid = contents.get("pid")

    if not (isinstance(host, str) and isinstance(port, int) and isinstance(pid, int)):
        return None

    return Instance(host=host, port=port, pid=pid)


def fetch_status(instance: Instance) -> dict | None:
    # An IPv6 address needs brackets in a URL
    host = f"[{instance.host}]" if ":" in instance.host else instance.host
    try:
        response = requests.get(f"http://{host}:{instance.port}/status", timeout=2)
        if response.status_code != 200:
            return None
        return response.json()
    except (requests.RequestException, ValueError):
        return None


def instance_answers(instance: Instance) -> bool:
    return fetch_status(instance) is not None


def stop_instance(status: Callable[[Instance], dict | None] = fetch_status) -> bool:
    instance = read_instance()
    if instance is None:
        return False

    # Delete the file first, so a failed stop never leaves a file pointing
    # at a dead or reused process
    instance_file_path().unlink(missing_ok=True)

    current_status = status(instance)
    if current_status is None or current_status.get("pid") != instance.pid:
        return True

    try:
        psutil.Process(instance.pid).terminate()
    except psutil.NoSuchProcess:
        pass

    return True


def claim_start(
    bind: Callable[[], Instance],
    answers: Callable[[Instance], bool] = instance_answers,
) -> Instance | None:
    # The lock covers checking and binding, so two starts at once make one
    # instance, and it ends before serving starts.
    with FileLock(f"{instance_file_path()}.lock"):
        existing = read_instance()
        if existing is not None and answers(existing):
            return existing

        instance = bind()
        write_instance(instance)
        return None
