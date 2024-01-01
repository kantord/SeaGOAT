import os
import socket
import subprocess
from pathlib import Path
from typing import Dict, TypedDict, Union

import appdirs
import psutil

from seagoat.utils.json_file import get_json_file_contents, write_to_json_file


class ServerInfo(TypedDict):
    address: str
    host: str
    port: int
    pid: int


class ServerDoesNotExist(Exception):
    pass


def _get_server_data_file_path() -> Path:
    user_cache_dir = Path(appdirs.user_cache_dir("seagoat-servers"))
    user_cache_dir.mkdir(parents=True, exist_ok=True)
    return user_cache_dir / "serverData.json"


def normalize_repo_path(repo_path: Union[str, Path]) -> str:
    return str(os.path.normpath(Path(repo_path).expanduser().resolve()))


def get_servers_info() -> Dict[str, ServerInfo]:
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


def update_server_info(
    repo_path: Union[str, Path], new_server_data: ServerInfo
) -> None:
    servers_info = get_servers_info()
    repo_id = normalize_repo_path(repo_path)
    servers_info[repo_id] = new_server_data

    write_to_json_file(_get_server_data_file_path(), servers_info)


def stop_server(repo_path: Union[str, Path]) -> None:
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


def get_server_info(repo_path: Union[str, Path]) -> ServerInfo:
    servers_info = get_servers_info()
    repo_id = normalize_repo_path(repo_path)

    if repo_id not in servers_info:
        raise ServerDoesNotExist(f"Server for {repo_path} does not exist.")

    server_info = servers_info[repo_id]
    return server_info


def is_server_running(repo_path: Union[str, Path]) -> bool:
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
