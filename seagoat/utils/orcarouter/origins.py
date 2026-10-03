"""Origin resolution for the two OrcaRouter surfaces.

OrcaRouter splits authentication and inference across two public origins:

* authentication / code exchange — ``https://www.orcarouter.ai``
* inference / model discovery — ``https://api.orcarouter.ai/v1``

Neither origin may be derived from the other by swapping the hostname or by
appending ``/v1``; they are configured independently. A self-hosted
deployment may instead expose both surfaces on a single shared origin.
"""

import os
from typing import Mapping, Optional
from urllib.parse import urlparse

DEFAULT_AUTH_BASE = "https://www.orcarouter.ai"
DEFAULT_API_BASE = "https://api.orcarouter.ai/v1"

AUTHORIZE_PATH = "/auth"
EXCHANGE_PATH = "/api/v1/auth/keys"

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}

_ENV_AUTH = "ORCA_AUTH_BASE_URL"
_ENV_API = "ORCA_API_BASE_URL"
_ENV_SHARED = "ORCA_BASE_URL"


class OriginError(ValueError):
    """Raised when a configured origin is not a usable HTTP(S) base."""


def _first_non_empty(*values) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _normalize(base: Optional[str]) -> Optional[str]:
    if not base:
        return None
    return base.rstrip("/")


def _is_loopback(hostname: str) -> bool:
    return hostname.lower() in _LOOPBACK_HOSTS


def validate_origin(base: str) -> str:
    """Validate that ``base`` is an https URL, or http on loopback only."""
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OriginError(f"Invalid OrcaRouter origin: {base!r}")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise OriginError(
            "OrcaRouter origins must use https; "
            f"plain http is only allowed for loopback, got {base!r}"
        )
    return base


def resolve_api_base(
    generative_config: Optional[Mapping[str, object]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve the inference base URL.

    Explicit ``apiBaseUrl`` (config) and ``ORCA_API_BASE_URL`` (env) take
    precedence over the shared ``baseUrl`` / ``ORCA_BASE_URL`` fallback.
    """
    config = generative_config or {}
    env = environ if environ is not None else os.environ
    base = _first_non_empty(
        config.get("apiBaseUrl") if isinstance(config, Mapping) else None,
        env.get(_ENV_API),
        config.get("baseUrl") if isinstance(config, Mapping) else None,
        env.get(_ENV_SHARED),
        DEFAULT_API_BASE,
    )
    return validate_origin(_normalize(base) or DEFAULT_API_BASE)


def resolve_auth_base(
    generative_config: Optional[Mapping[str, object]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve the authentication base URL.

    Explicit ``authBaseUrl`` (config) and ``ORCA_AUTH_BASE_URL`` (env) take
    precedence over the shared ``baseUrl`` / ``ORCA_BASE_URL`` fallback.
    """
    config = generative_config or {}
    env = environ if environ is not None else os.environ
    base = _first_non_empty(
        config.get("authBaseUrl") if isinstance(config, Mapping) else None,
        env.get(_ENV_AUTH),
        config.get("baseUrl") if isinstance(config, Mapping) else None,
        env.get(_ENV_SHARED),
        DEFAULT_AUTH_BASE,
    )
    return validate_origin(_normalize(base) or DEFAULT_AUTH_BASE)


def authorize_url_base(auth_base: str) -> str:
    return f"{auth_base.rstrip('/')}{AUTHORIZE_PATH}"


def exchange_url(auth_base: str) -> str:
    """The code-exchange endpoint.

    It lives on the authentication origin under ``/api/v1/auth``. The relay
    origin's ``/v1/auth/keys`` path does not exist.
    """
    return f"{auth_base.rstrip('/')}{EXCHANGE_PATH}"


def models_url(api_base: str, capability: Optional[str] = None) -> str:
    url = f"{api_base.rstrip('/')}/models"
    if capability:
        url = f"{url}?capability={capability}"
    return url
