"""Persistent storage for an OrcaRouter credential.

The key is written into SeaGOAT's existing global configuration file — the
same place the project already keeps provider secrets — under
``generative.apiKey``. No new secret store or side file is introduced. The
file is tightened to owner-only permissions because it now holds a key.
"""

import os
from pathlib import Path
from typing import Mapping, Optional

import yaml

from seagoat.utils.config import GLOBAL_CONFIG_FILE

# Records how the stored key was obtained so a status command can label it.
# Nothing branches on this for requests; both sources yield the same key.
SOURCE_KEY = "apiKeySource"

ENV_API_KEY = "ORCAROUTER_API_KEY"
SOURCE_API_KEY = "api_key"
SOURCE_PKCE = "pkce"

OWNER_ONLY = 0o600


def config_file() -> Path:
    return GLOBAL_CONFIG_FILE


def _load() -> dict:
    path = config_file()
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _save(data: Mapping) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(dict(data), sort_keys=True), encoding="utf-8")
    os.chmod(tmp, OWNER_ONLY)
    os.replace(tmp, path)
    os.chmod(path, OWNER_ONLY)


def read_record() -> dict:
    """The stored OrcaRouter credential, if any, without other config keys."""
    generative = _load().get("generative") or {}
    key = generative.get("apiKey")
    if not key:
        return {}
    return {"api_key": key, "source": generative.get(SOURCE_KEY) or SOURCE_API_KEY}


def write_record(record: Mapping) -> None:
    """Persist the credential into the existing global config file."""
    data = _load()
    generative = data.setdefault("generative", {})
    generative["apiKey"] = record["api_key"]
    generative[SOURCE_KEY] = record.get("source") or SOURCE_API_KEY
    _save(data)


def clear_record() -> bool:
    """Forget the stored credential. Returns True when something was removed."""
    data = _load()
    generative = data.get("generative")
    if not isinstance(generative, dict) or not generative.get("apiKey"):
        return False
    generative.pop("apiKey", None)
    generative.pop(SOURCE_KEY, None)
    _save(data)
    return True


def stored_key() -> Optional[str]:
    return read_record().get("api_key")


def resolve_api_key(
    config: Optional[Mapping] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Resolve the key for the OrcaRouter provider, whatever issued it.

    Precedence: explicit config ``apiKey``, then ``ORCAROUTER_API_KEY``, then
    the key stored by the connect flow.
    """
    env = environ if environ is not None else os.environ
    return (config or {}).get("apiKey") or env.get(ENV_API_KEY) or stored_key()


def resolve_source_kind(
    config: Optional[Mapping] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Where the key would come from, without revealing the key itself."""
    env = environ if environ is not None else os.environ
    if env.get(ENV_API_KEY):
        return SOURCE_API_KEY
    if (config or {}).get("apiKey"):
        return (config or {}).get(SOURCE_KEY) or SOURCE_API_KEY
    if stored_key():
        return read_record().get("source") or SOURCE_API_KEY
    return None
