import json
import os

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
