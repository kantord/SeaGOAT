"""The credential seam.

API-key paste and OAuth 2.0 + PKCE are two adapters over one interface. Both
produce the same :class:`Credential`, so the inference adapter and the model
catalog never learn where the key came from.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

API_KEY_PREFIX = "sk-orca-"

# A durable OrcaRouter key is not a refresh token; there is no refresh grant.
# These states are the terminal classifications the credential can carry.
STATE_READY = "ready"
STATE_NEEDS_REAUTH = "needs_reauth"


class CredentialError(Exception):
    """Raised for a login that cannot produce a credential."""


@dataclass
class Credential:
    """A resolved OrcaRouter credential plus its provenance.

    ``source`` is ``"api_key"`` or ``"pkce"`` and is informational only: no
    HTTP call ever branches on it.
    """

    api_key: str
    source: str
    generation: int = 1
    state: str = STATE_READY
    scope: Optional[str] = None
    account_id: Optional[str] = None
    issued_at: float = field(default_factory=time.time)

    def masked(self) -> str:
        return mask_secret(self.api_key)

    def redacted(self, text: str) -> str:
        """Replace this key wherever it appears in ``text``."""
        if not self.api_key:
            return text
        return text.replace(self.api_key, self.masked())


def mask_secret(secret: Optional[str]) -> str:
    """Mask a secret for display. Never returns the middle of the key."""
    if not secret:
        return ""
    if len(secret) <= 10:
        return "*" * len(secret)
    return f"{secret[:7]}...{secret[-4:]}"


def looks_like_api_key(value: Optional[str]) -> bool:
    """A lightweight shape check, not proof of validity."""
    return bool(value) and value.startswith(API_KEY_PREFIX)


@runtime_checkable
class CredentialSource(Protocol):
    """Anything that can resolve an OrcaRouter credential on demand."""

    name: str

    def resolve(self) -> Credential:
        ...


class ApiKeyCredentialSource:
    """Adapter for a pasted/config/env ``sk-orca-...`` key."""

    name = "api_key"

    def __init__(self, api_key_provider, provenance: str = "api_key"):
        self._api_key_provider = api_key_provider
        self._provenance = provenance

    def resolve(self) -> Credential:
        key = self._api_key_provider()
        if not key:
            raise CredentialError(
                "No OrcaRouter API key is configured. Paste one with "
                "`gt orcarouter-login --api-key`, or connect with "
                "`gt orcarouter-login`."
            )
        if not looks_like_api_key(key):
            raise CredentialError(
                "That value does not look like an OrcaRouter API key "
                f"(expected it to start with {API_KEY_PREFIX!r})."
            )
        return Credential(api_key=key, source=self._provenance)


class PkceCredentialSource:
    """Adapter for a key issued by the OAuth 2.0 + PKCE connect flow."""

    name = "pkce"

    def __init__(self, connect):
        self._connect = connect

    def resolve(self) -> Credential:
        payload = self._connect()
        return Credential(
            api_key=payload["key"],
            source=self.name,
            scope=payload.get("scope"),
            account_id=payload.get("user_id"),
        )


class CredentialState:
    """Generation-safe ``needsReauth`` bookkeeping for one credential.

    A late ``401`` from a request made with generation *N* must never mark
    the credential that replaced it (generation *N+1*) as broken.
    """

    def __init__(self):
        self.generation = 0
        self.state = STATE_READY
        self.source: Optional[str] = None

    def adopt(self, credential: Credential) -> Credential:
        """Install a freshly obtained credential as the current generation.

        The stored secret is not deleted by this call; the caller only swaps
        it in after a successful login.
        """
        self.generation += 1
        self.state = STATE_READY
        self.source = credential.source
        credential.generation = self.generation
        credential.state = STATE_READY
        return credential

    def mark_unauthorized(self, generation: Optional[int] = None) -> bool:
        """Mark the credential that made a rejected request as needing reauth.

        Returns ``True`` when the state changed. A stale generation is
        ignored so it cannot poison a newer credential.
        """
        if self.state != STATE_READY:
            return False
        if generation is not None and generation != self.generation:
            return False
        self.state = STATE_NEEDS_REAUTH
        return True

    @property
    def needs_reauth(self) -> bool:
        return self.state == STATE_NEEDS_REAUTH
