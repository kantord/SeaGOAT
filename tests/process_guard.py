"""Helpers that make child processes die with the test run.

On Linux, children ask the kernel to SIGTERM them if their parent dies
(PR_SET_PDEATHSIG), so even a SIGKILLed pytest cannot leave servers or
subprocesses behind.

This module must stay free of side effects (no conftest import, no seagoat
import at module level).
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
