"""OrcaRouter connect flow: authorize, receive the code, exchange it.

The exchange endpoint lives on the authentication origin and returns a
durable OrcaRouter API key. The key is *not* an OAuth refresh token: there is
no refresh grant and nothing here schedules a proactive refresh.
"""

import http.server
import threading
import webbrowser
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

import requests

from seagoat.utils.orcarouter.origins import exchange_url
from seagoat.utils.orcarouter.pkce import (
    APP_NAME,
    FLOW_LOOPBACK,
    FLOW_OOB,
    SCOPE_API,
    PkceAttempt,
    PkceError,
    create_attempt,
    extract_key,
    read_granted_scope,
    states_match,
)

CALLBACK_OOB = "oob"
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PATH = "/cb"

DEFAULT_TIMEOUT = 30.0


class ConnectError(PkceError):
    """A connect failure safe to show the user (never carries a credential)."""


def exchange_code(
    auth_base: str,
    body: dict,
    timeout: float = DEFAULT_TIMEOUT,
    session: Optional[requests.Session] = None,
) -> dict:
    """POST the auth code + verifier to the exchange endpoint."""
    sender = session or requests
    try:
        response = sender.post(
            exchange_url(auth_base),
            json=body,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
    except requests.exceptions.Timeout as error:
        raise ConnectError(
            "The OrcaRouter authorization exchange timed out; run the login again."
        ) from error
    except requests.exceptions.RequestException as error:
        raise ConnectError(
            "Could not reach OrcaRouter to exchange the authorization code."
        ) from error

    if response.status_code == 200:
        try:
            payload = response.json()
        except ValueError as error:
            raise ConnectError(
                "OrcaRouter returned a malformed authorization response."
            ) from error
        read_granted_scope(payload)
        extract_key(payload)
        return payload

    if response.status_code in (400, 403):
        raise ConnectError(
            "OrcaRouter rejected the authorization code "
            "(unknown, expired, already used, or verifier mismatch)."
        )
    if response.status_code == 429:
        raise ConnectError(
            "OrcaRouter rate-limited this authorization. You can issue at most "
            "10 keys per 24 hours; wait a moment and try again."
        )
    if response.status_code >= 500:
        raise ConnectError(
            f"OrcaRouter authorization failed with a server error "
            f"({response.status_code}); try again later."
        )
    raise ConnectError(f"OrcaRouter authorization failed ({response.status_code}).")


class LoopbackReceiver:
    """A one-shot HTTP listener on loopback that captures the redirect."""

    def __init__(self, host: str = LOOPBACK_HOST):
        self.host = host
        self.port: Optional[int] = None
        self._server: Optional[http.server.HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._done = threading.Event()
        self._raw_query: Optional[str] = None

    @property
    def callback_url(self) -> str:
        if self.port is None:
            raise ConnectError("The loopback listener is not running yet")
        return f"http://{self.host}:{self.port}{LOOPBACK_PATH}"

    def __enter__(self) -> "LoopbackReceiver":
        receiver = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                parsed = urlparse(self.path)
                if parsed.path != LOOPBACK_PATH:
                    self.send_response(404)
                    self.end_headers()
                    return
                receiver._raw_query = parsed.query
                body = (
                    b"<html><body><p>SeaGOAT is connected. "
                    b"You can close this tab.</p></body></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                receiver._done.set()

            def log_message(self, *_args):
                return

        self._server = http.server.HTTPServer((self.host, 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return False

    def wait(self, expected_state: str, timeout: float) -> str:
        """Block until the browser hits the callback, then return the code."""
        if not self._done.wait(timeout):
            raise ConnectError(
                "Timed out waiting for the browser to return the authorization code."
            )
        params = parse_qs(self._raw_query or "")
        received_state = (params.get("state") or [None])[0]
        if not states_match(expected_state, received_state):
            raise ConnectError(
                "The authorization response failed the state check and was ignored."
            )
        error = (params.get("error") or [None])[0]
        if error:
            raise ConnectError(f"OrcaRouter denied the authorization ({error}).")
        code = (params.get("code") or [None])[0]
        if not code:
            raise ConnectError("The authorization response carried no code.")
        return code


def _open_browser(url: str, opener: Callable[[str], bool] = webbrowser.open) -> bool:
    try:
        return bool(opener(url))
    except Exception:
        return False


def connect(
    auth_base: str,
    flow: str = FLOW_OOB,
    *,
    app_name: str = APP_NAME,
    scope: str = SCOPE_API,
    timeout: float = DEFAULT_TIMEOUT,
    prompt: Callable[[str], str] = input,
    opener: Callable[[str], bool] = webbrowser.open,
    announce: Callable[[str], None] = print,
    session: Optional[requests.Session] = None,
) -> dict:
    """Run a connect flow and return ``{"key", "scope", "user_id"}``.

    ``flow`` is ``FLOW_OOB`` (default) or ``FLOW_LOOPBACK``.
    """
    if flow == FLOW_LOOPBACK:
        return _connect_loopback(
            auth_base,
            app_name=app_name,
            scope=scope,
            timeout=timeout,
            opener=opener,
            announce=announce,
            session=session,
        )
    if flow == FLOW_OOB:
        return _connect_oob(
            auth_base,
            app_name=app_name,
            scope=scope,
            timeout=timeout,
            prompt=prompt,
            opener=opener,
            announce=announce,
            session=session,
        )
    raise ConnectError(f"Unknown OrcaRouter connect flow: {flow}")


def _finish(attempt: PkceAttempt, code: str, auth_base, timeout, session, announce):
    announce("Exchanging the authorization code for an OrcaRouter key...")
    payload = exchange_code(
        auth_base, attempt.exchange_body(code), timeout=timeout, session=session
    )
    return payload


def _connect_oob(
    auth_base,
    *,
    app_name,
    scope,
    timeout,
    prompt,
    opener,
    announce,
    session,
) -> dict:
    attempt = create_attempt(auth_base, CALLBACK_OOB, app_name=app_name, scope=scope)
    announce(
        "Authorize SeaGOAT in your browser, then paste the code back here:\n"
        + attempt.authorize_url
    )
    if not _open_browser(attempt.authorize_url, opener):
        announce("Could not open a browser automatically; open the URL above.")
    code = (prompt("Code: ") or "").strip()
    if not code:
        raise ConnectError("No authorization code was entered.")
    return _finish(attempt, code, auth_base, timeout, session, announce)


def _connect_loopback(
    auth_base,
    *,
    app_name,
    scope,
    timeout,
    opener,
    announce,
    session,
) -> dict:
    with LoopbackReceiver() as receiver:
        attempt = create_attempt(
            auth_base, receiver.callback_url, app_name=app_name, scope=scope
        )
        announce("Opening your browser to authorize SeaGOAT:\n" + attempt.authorize_url)
        if not _open_browser(attempt.authorize_url, opener):
            announce("Could not open a browser automatically; open the URL above.")
        code = receiver.wait(attempt.state, timeout)
    return _finish(attempt, code, auth_base, timeout, session, announce)
