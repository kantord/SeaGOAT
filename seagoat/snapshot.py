"""
Query snapshots: the coherent, immutable state one query reads.

Ownership and lifetime contract
-------------------------------
A :class:`QuerySnapshot` bundles a ``RepositorySnapshot`` (rankings, file/object
metadata) with the per-source states built from it (e.g. the ripgrep contents
and line mappings). It is reference counted:

* The publisher (the Engine) owns one reference while the snapshot is current.
* Every query takes its own reference with :meth:`QuerySnapshot.acquire`
  (through ``Engine``, which does it atomically with reading the current
  snapshot) and drops it with :meth:`QuerySnapshot.release`.
* Publishing a replacement drops the publisher's reference to the old one. The
  old snapshot stays fully usable until its last reader releases it, and only
  then are its resources (mappings, files) closed.

A snapshot is never mutated after construction and a retired snapshot's
resources are never truncated or replaced in place, so an in-flight reader
cannot observe a partial or changed state.
"""

import logging
import threading
from collections.abc import Mapping
from typing import Any, Protocol, Self

from seagoat.repository import RepositorySnapshot

logger = logging.getLogger(__name__)


class SourceState(Protocol):
    """Per-source state built from a repository snapshot."""

    def close(self) -> None: ...


class QuerySnapshot:
    def __init__(
        self,
        repository: RepositorySnapshot,
        states: Mapping[int, SourceState | None],
    ):
        self.repository = repository
        # Keyed by the identity of the source dict that built each state
        self._states = dict(states)
        self._lock = threading.Lock()
        self._refs = 1
        self._closed = False

    def state_for(self, source: Any) -> Any:
        return self._states.get(id(source))

    def acquire(self) -> "QuerySnapshot":
        with self._lock:
            if self._refs <= 0:
                raise RuntimeError("snapshot was already released")
            self._refs += 1
        return self

    def release(self) -> None:
        with self._lock:
            self._refs -= 1
            if self._refs > 0 or self._closed:
                return
            self._closed = True
        self._close_states()

    @property
    def closed(self) -> bool:
        return self._closed

    def _close_states(self) -> None:
        for state in self._states.values():
            if state is None:
                continue
            try:
                state.close()
            except Exception:
                logger.exception("failed to release snapshot resources")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        self.release()
