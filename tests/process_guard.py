"""Helpers that make child processes die with the test run.

On Linux, children ask the kernel to SIGTERM them if their parent dies
(PR_SET_PDEATHSIG), so even a SIGKILLed pytest cannot leave servers or
subprocesses behind.

This module is imported by the forkserver worker, so it must stay free of
side effects (no conftest import, no seagoat import at module level).
"""

import ctypes
import signal
import sys

PR_SET_PDEATHSIG = 1


def set_pdeathsig() -> None:
    """Ask the kernel to SIGTERM this process if its parent dies.

    PR_SET_PDEATHSIG is Linux-specific; elsewhere this is a no-op.
    """
    if sys.platform != "linux":
        return
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def start_server_with_pdeathsig(repo_path: str) -> None:
    """Run seagoat.server.start_server, dying with the test run on Linux."""
    set_pdeathsig()
    from seagoat.server import start_server

    start_server(repo_path)
