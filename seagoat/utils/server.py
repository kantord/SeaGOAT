import os
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import psutil
import requests
from filelock import FileLock

from seagoat.utils.json_file import get_json_file_contents, write_to_json_file
from seagoat.utils.paths import get_servers_dir


class NoInstanceRunning(Exception):
    pass


def normalize_repo_path(repo_path: str | Path) -> str:
    return str(
        os.path.normcase(os.path.normpath(Path(repo_path).expanduser().resolve()))
    )


class Instance(NamedTuple):
    host: str  # the address clients use
    port: int
    pid: int


def instance_file_path() -> Path:
    servers_dir = get_servers_dir()
    servers_dir.mkdir(parents=True, exist_ok=True)
    return servers_dir / "instance.json"


def repositories_file_path() -> Path:
    return instance_file_path().parent / "repositories.json"


def add_repository(repo_path) -> bool:
    # Imported here because seagoat.projects imports seagoat.utils.server
    from seagoat.projects import resolve_repo_path

    repositories = read_repositories()
    normalized_path = normalize_repo_path(resolve_repo_path(repo_path))

    if any(normalize_repo_path(path) == normalized_path for path in repositories):
        return False

    repositories.append(normalized_path)
    write_to_json_file(repositories_file_path(), repositories)
    return True


def read_repositories() -> list[str]:
    try:
        repositories = get_json_file_contents(repositories_file_path())
    except (OSError, ValueError):
        return []

    if not isinstance(repositories, list):
        return []

    return [path for path in repositories if isinstance(path, str)]


def client_host(host: str) -> str:
    """The address a client on this machine uses for an instance bound to host.

    This never binds: it maps a wildcard bind address to its loopback address.
    """
    return {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)  # nosec B104


def write_instance(instance: Instance) -> None:
    host = client_host(instance.host)

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


def running_instance() -> tuple[Instance, dict] | None:
    """The instance from the instance file with its /status answer, but only
    when that answer comes from the very pid the file names."""
    instance = read_instance()
    if instance is None:
        return None

    status = fetch_status(instance)
    if status is None or status.get("pid") != instance.pid:
        return None

    return instance, status


def stop_instance() -> tuple[str, int | None]:
    """
    Stop the instance named by the instance file, if any.

    Returns an outcome and, for a failed verification, the pid from the file:

        ("stopped", None)     - the process was verified as SeaGOAT and
                                terminated;
        ("not_running", None) - there is no instance file, or the process it
                                names is gone or is not SeaGOAT (the stale
                                file is removed);
        ("failed", pid)       - the process could not be inspected
                                (AccessDenied); the instance file is kept so
                                the caller can report the pid and not claim
                                success.
    """
    instance = read_instance()
    if instance is None:
        return "not_running", None

    # Terminate the pid only if that process exists and its command line runs
    # seagoat-server, so a reused pid of an unrelated process is never killed.
    try:
        process = psutil.Process(instance.pid)
        if not process.is_running():
            instance_file_path().unlink(missing_ok=True)
            return "not_running", None
        cmdline = " ".join(process.cmdline())
    except psutil.NoSuchProcess:
        instance_file_path().unlink(missing_ok=True)
        return "not_running", None
    except psutil.AccessDenied:
        return "failed", instance.pid

    if "seagoat-server" not in cmdline and "seagoat.server" not in cmdline:
        # The pid was reused by an unrelated process: the instance is gone
        instance_file_path().unlink(missing_ok=True)
        return "not_running", None

    process.terminate()
    if not _exited(process, timeout=5):
        process.kill()
        _exited(process, timeout=5)
    instance_file_path().unlink(missing_ok=True)
    return "stopped", None


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
    prepare: Callable[[], None] | None = None,
) -> Instance | None:
    # The lock covers preparing, checking and binding, so two starts at once
    # make one instance, and it ends before serving starts.
    with FileLock(f"{instance_file_path()}.lock"):
        if prepare is not None:
            prepare()

        running = running_instance()
        if running is not None:
            return running[0]

        instance = bind()
        write_instance(instance)
        return None
