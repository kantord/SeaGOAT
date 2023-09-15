import os
import socket
from pathlib import Path

import appdirs

from seagoat.utils.json_file import get_json_file_contents
from seagoat.utils.json_file import write_to_json_file


class ServerDoesNotExist(Exception):
    pass


def _get_server_data_file_path() -> Path:
    user_cache_dir = Path(appdirs.user_cache_dir("seagoat-servers"))
    user_cache_dir.mkdir(parents=True, exist_ok=True)
    return user_cache_dir / "serverData.json"


def _get_repo_id(repo_path: str) -> str:
    return str(Path(repo_path).resolve())


def get_servers_info() -> dict:
    path = _get_server_data_file_path()
    if not os.path.exists(path):
        write_to_json_file(path, {})

    return get_json_file_contents(path)


def update_server_info(repo_path: str, new_server_data: dict) -> None:
    servers_info = get_servers_info()
    repo_id = _get_repo_id(repo_path)
    servers_info[repo_id] = new_server_data

    write_to_json_file(_get_server_data_file_path(), servers_info)


def remove_server_info(repo_path: str) -> None:
    servers_info = get_servers_info()
    repo_id = _get_repo_id(repo_path)
    if repo_id in servers_info:
        servers_info.pop(repo_id)
        write_to_json_file(_get_server_data_file_path(), servers_info)
    else:
        raise ServerDoesNotExist(f"Server for {repo_path} does not exist.")


def get_server_info(repo_path: str) -> dict:
    servers_info = get_servers_info()
    repo_id = _get_repo_id(repo_path)

    if repo_id not in servers_info:
        raise ServerDoesNotExist(f"Server for {repo_path} does not exist.")

    server_info = servers_info[repo_id]
    server_info["address"] = f"http://{server_info['host']}:{server_info['port']}"
    return server_info


def is_server_running(repo_path: str):
    try:
        server_info = get_server_info(repo_path)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_obj:
            return (
                socket_obj.connect_ex((server_info["host"], server_info["port"])) == 0
            )
    except ServerDoesNotExist:
        return False


def get_free_port():
    socket_obj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_obj.bind(("", 0))
    _, port = socket_obj.getsockname()
    socket_obj.close()

    return port
