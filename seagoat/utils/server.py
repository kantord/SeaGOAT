import os
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import platformdirs
import psutil
import requests
from filelock import FileLock

from seagoat.utils.json_file import get_json_file_contents, write_to_json_file


class ServerDoesNotExist(Exception):
    pass


def normalize_repo_path(repo_path: str | Path) -> str:
    return str(
        os.path.normcase(os.path.normpath(Path(repo_path).expanduser().resolve()))
    )


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


def instance_url(instance: Instance) -> str:
    # An IPv6 address needs brackets in a URL
    host = f"[{instance.host}]" if ":" in instance.host else instance.host
    return f"http://{host}:{instance.port}"


def fetch_status(instance: Instance) -> dict | None:
    try:
        response = requests.get(f"{instance_url(instance)}/status", timeout=2)
        if response.status_code != 200:
            return None
        return response.json()
    except (requests.RequestException, ValueError):
        return None


def instance_answers(instance: Instance) -> bool:
    return fetch_status(instance) is not None


def stop_instance() -> bool:
    instance = read_instance()
    if instance is None:
        return False

    # Delete the file first, so a failed stop never leaves a file pointing
    # at a dead or reused process
    instance_file_path().unlink(missing_ok=True)

    # Terminate the pid only if that process exists and its command line runs
    # seagoat-server, so a reused pid of an unrelated process is never killed.
    try:
        process = psutil.Process(instance.pid)
        if not process.is_running():
            return True
        cmdline = " ".join(process.cmdline())
        if "seagoat-server" not in cmdline and "seagoat.server" not in cmdline:
            return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True

    process.terminate()
    if not _exited(process, timeout=5):
        process.kill()
        _exited(process, timeout=5)
    return True


def _exited(process: psutil.Process, timeout: float) -> bool:
    # An exited process its parent has not reaped yet is a zombie: it has
    # stopped, but psutil still waits for it to disappear
    try:
        process.wait(timeout=timeout)
    except psutil.TimeoutExpired:
        try:
            return process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return True
    return True


def claim_start(
    bind: Callable[[], Instance],
    answers: Callable[[Instance], bool] = instance_answers,
    prepare: Callable[[], None] | None = None,
) -> Instance | None:
    # The lock covers preparing, checking and binding, so two starts at once
    # make one instance, and it ends before serving starts.
    with FileLock(f"{instance_file_path()}.lock"):
        if prepare is not None:
            prepare()

        existing = read_instance()
        if existing is not None and answers(existing):
            return existing

        instance = bind()
        write_instance(instance)
        return None
