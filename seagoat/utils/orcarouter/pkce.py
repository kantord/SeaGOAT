"""OAuth 2.0 + PKCE helpers for the OrcaRouter connect flow.

Two flows are supported:

* **Flow A — loopback redirect**: the CLI listens on ``127.0.0.1`` and the
  browser hands the one-time code back automatically.
* **Flow B — out-of-band code**: ``callback_url=oob``; the consent screen
  shows a code the user pastes back. This is the default because SeaGOAT is
  frequently run as a headless daemon or over SSH where no loopback listener
  is reachable from the browser.

Both flows always send an ``S256`` challenge. No client secret is involved.

A verifier and a state value are generated with the OS CSPRNG for every
attempt. The verifier never leaves this process until the exchange request
body, and must never be written to a URL, a log, or an exception message.
"""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from seagoat.utils.orcarouter.origins import authorize_url_base

APP_NAME = "SeaGOAT"

FLOW_LOOPBACK = "loopback"
FLOW_OOB = "oob"

SCOPE_API = "api"


class PkceError(Exception):
    """A connect-flow failure that carries no credential material."""


def _b64url(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@dataclass(frozen=True)
class PkceAttempt:
    """One authorization attempt.

    ``verifier`` is secret; ``authorize_url`` is safe to print.
    """

    verifier: str
    state: str
    code_challenge: str
    authorize_url: str
    callback_url: str

    def exchange_body(self, code: str) -> dict:
        return {
            "code": code,
            "code_verifier": self.verifier,
            "code_challenge_method": "S256",
        }


def create_attempt(
    auth_base: str,
    callback_url: str,
    app_name: str = APP_NAME,
    scope: str = SCOPE_API,
) -> PkceAttempt:
    """Build a fresh PKCE attempt.

    ``callback_url`` is either the literal ``oob`` (Flow B) or an explicit
    loopback URL (Flow A).
    """
    if not callback_url:
        raise PkceError("A callback_url is required")

    verifier = _b64url(secrets.token_bytes(32))
    state = _b64url(secrets.token_bytes(16))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())

    params = [
        ("callback_url", callback_url),
        ("code_challenge", challenge),
        ("code_challenge_method", "S256"),
        ("state", state),
        ("app_name", app_name),
        ("scope", scope),
    ]
    query = "&".join(f"{key}={quote(str(value), safe='')}" for key, value in params)
    return PkceAttempt(
        verifier=verifier,
        state=state,
        code_challenge=challenge,
        authorize_url=f"{authorize_url_base(auth_base)}?{query}",
        callback_url=callback_url,
    )


def states_match(expected: str, received: Optional[str]) -> bool:
    """Constant-time comparison of the echoed ``state`` parameter."""
    if not received:
        return False
    return secrets.compare_digest(expected, received)


def read_granted_scope(payload: dict, requested: str = SCOPE_API) -> str:
    """Return the granted scope, warning when it is narrower than requested.

    The exchange response reports what was *granted*, which may be less than
    what the authorize request asked for. Never treat the requested scope as
    granted.
    """
    granted = payload.get("scope")
    if not granted:
        raise PkceError("The OrcaRouter authorization response carried no scope")
    if granted != requested:
        raise PkceError(
            f'OrcaRouter granted scope "{granted}", not the requested '
            f'"{requested}"; this authorization cannot be used here'
        )
    return granted


def extract_key(payload: dict) -> str:
    key = payload.get("key")
    if not key or not isinstance(key, str):
        raise PkceError("The OrcaRouter authorization response carried no key")
    return key
