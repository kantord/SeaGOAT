"""The test suite's processes are guarded against the outside world:

- network is blocked except localhost and the embedding model host;
- secrets are removed from the environment;
- managed_process kills the whole process group when the test ends.
"""

import os
import subprocess
import sys

import psutil
import pytest
import requests

from seagoat.utils.wait import wait_for


def test_network_blocked_in_process():
    with pytest.raises(
        (requests.exceptions.ProxyError, requests.exceptions.ConnectionError)
    ):
        requests.get("https://example.com", timeout=5)


def test_network_blocked_in_subprocess():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import requests; requests.get('https://example.com', timeout=5)",
        ],
        check=False,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode != 0


def test_no_secret_environment_variables_remain():
    assert not [
        name
        for name in os.environ
        if name.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))
        or name.startswith("AWS_")
    ]


def test_managed_process_kills_whole_process_group(managed_process):
    with managed_process(["sh", "-c", "sleep 60 & wait"]) as proc:
        # `sleep` runs as a child of the shell, in the same process group
        wait_for(lambda: len(psutil.Process(proc.pid).children()) > 0, timeout=5)
        grandchild_pids = [child.pid for child in psutil.Process(proc.pid).children()]
        assert grandchild_pids

    # After the with block the whole group is dead: no child of the shell
    # survives. The orphaned `sleep` may linger as a zombie until init reaps
    # it, which is dead too.
    def is_dead(pid):
        try:
            return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return True

    for pid in grandchild_pids:
        wait_for(lambda pid=pid: is_dead(pid), timeout=5)
