from pathlib import Path

import platformdirs

from seagoat.utils.paths import get_cache_dir, get_config_dir, get_servers_dir


def test_overrides_use_environment_variables(monkeypatch):
    monkeypatch.setenv("SEAGOAT_CACHE_DIR", "/tmp/seagoat-cache")
    monkeypatch.setenv("SEAGOAT_CONFIG_DIR", "/tmp/seagoat-config")

    assert str(get_cache_dir()) == "/tmp/seagoat-cache"
    assert str(get_config_dir()) == "/tmp/seagoat-config"
    assert str(get_servers_dir()) == "/tmp/seagoat-cache/servers"


def test_without_overrides_uses_platformdirs(monkeypatch):
    monkeypatch.delenv("SEAGOAT_CACHE_DIR", raising=False)
    monkeypatch.delenv("SEAGOAT_CONFIG_DIR", raising=False)

    assert get_cache_dir() == Path(platformdirs.user_cache_dir("seagoat"))
    assert get_config_dir() == Path(platformdirs.user_config_dir("seagoat"))
    assert get_servers_dir() == Path(platformdirs.user_cache_dir("seagoat-servers"))
