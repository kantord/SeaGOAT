"""Lookup of SeaGOAT's cache and configuration directories.

Two environment variables override where SeaGOAT stores its per-repository
caches and its global configuration file:

- ``SEAGOAT_CACHE_DIR``: replaces ``platformdirs.user_cache_dir("seagoat")``
  when set. The instance file and repositories list then live under
  ``SEAGOAT_CACHE_DIR/servers`` instead of
  ``platformdirs.user_cache_dir("seagoat-servers")``.
- ``SEAGOAT_CONFIG_DIR``: replaces ``platformdirs.user_config_dir("seagoat")``
  when set.

They let tools (CI, test suites, containers) give SeaGOAT its own cache and
configuration directories even on platforms where platformdirs ignores the
``XDG_*`` environment variables (macOS and Windows).
"""

import os
from pathlib import Path

import platformdirs


def get_cache_dir() -> Path:
    override = os.environ.get("SEAGOAT_CACHE_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_cache_dir("seagoat"))


def get_config_dir() -> Path:
    override = os.environ.get("SEAGOAT_CONFIG_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_config_dir("seagoat"))


def get_servers_dir() -> Path:
    override = os.environ.get("SEAGOAT_CACHE_DIR")
    if override:
        return Path(override) / "servers"
    return Path(platformdirs.user_cache_dir("seagoat-servers"))
