import os
import socket

import appdirs

from seagoat.utils.json_file import get_json_file_contents


def get_server_info_file(repo_path):
    repo_id = os.path.normpath(repo_path).replace(os.sep, "_")
    user_cache_dir = appdirs.user_cache_dir("seagoat-servers")
    os.makedirs(user_cache_dir, exist_ok=True)
    return os.path.join(user_cache_dir, f"{repo_id}.json")


def get_server_info(repo_path: str):
    server_info = get_json_file_contents(get_server_info_file(repo_path))
    server_info["address"] = f"http://{server_info['host']}:{server_info['port']}"

    return server_info


def is_server_running(repo_path: str):
    server_info = get_server_info(repo_path)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_obj:
        return socket_obj.connect_ex((server_info["host"], server_info["port"])) == 0


def get_free_port():
    socket_obj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_obj.bind(("", 0))
    _, port = socket_obj.getsockname()
    socket_obj.close()

    return port
