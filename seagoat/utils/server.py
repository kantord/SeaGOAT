import json
import os
import socket

import appdirs


def get_server_info_file(repo_path):
    repo_id = os.path.normpath(repo_path).replace(os.sep, "_")
    user_cache_dir = appdirs.user_cache_dir("seagoat-servers")
    os.makedirs(user_cache_dir, exist_ok=True)
    return os.path.join(user_cache_dir, f"{repo_id}.json")


def load_server_info(server_info_file):
    with open(server_info_file, "r", encoding="utf-8") as file:
        server_info = json.load(file)
    host = server_info["host"]
    port = server_info["port"]
    pid = server_info.get("pid")
    server_address = f"http://{host}:{port}"
    return host, port, pid, server_address


def is_server_running(repo_path: str):
    server_info_file = get_server_info_file(repo_path)
    host, port, _, __ = load_server_info(server_info_file)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_obj:
        return socket_obj.connect_ex((host, port)) == 0
