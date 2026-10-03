"""Public entry points for the OrcaRouter integration.

This package owns the provider's credential acquisition (pasted API key or
OAuth 2.0 + PKCE), the durable key store, the split auth/inference origins,
and the capability-filtered model catalog. The rest of SeaGOAT talks to it
through :func:`resolve_credential`, :func:`discover_models` and
:func:`select_models`.
"""

from seagoat.utils.orcarouter.credentials import (
    API_KEY_PREFIX,
    STATE_NEEDS_REAUTH,
    STATE_READY,
    ApiKeyCredentialSource,
    Credential,
    CredentialError,
    CredentialSource,
    CredentialState,
    PkceCredentialSource,
    looks_like_api_key,
    mask_secret,
)
from seagoat.utils.orcarouter.origins import (
    AUTHORIZE_PATH,
    DEFAULT_API_BASE,
    DEFAULT_AUTH_BASE,
    EXCHANGE_PATH,
    authorize_url_base,
    exchange_url,
    models_url,
    resolve_api_base,
    resolve_auth_base,
)
from seagoat.utils.orcarouter.pkce import (
    FLOW_LOOPBACK,
    FLOW_OOB,
    PkceAttempt,
    PkceError,
    create_attempt,
    read_granted_scope,
    states_match,
)
from seagoat.utils.orcarouter.catalog import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDING,
    CAPABILITY_IMAGE,
    CAPABILITY_RERANK,
    CAPABILITY_VIDEO,
    CatalogResult,
    Model,
    SOURCE_LAST_KNOWN_GOOD,
    SOURCE_LIVE,
    SOURCE_SEED,
    VERIFIED_SEED,
    catalog_from_ids,
    discover,
    public_options,
    resolve_compatible,
    seed_models,
    select_for,
)
from seagoat.utils.orcarouter.oauth import ConnectError, connect, exchange_code
from seagoat.utils.orcarouter.store import (
    ENV_API_KEY,
    SOURCE_API_KEY,
    SOURCE_PKCE,
    clear_record,
    read_record,
    resolve_api_key,
    resolve_source_kind,
    write_record,
)

__all__ = [
    "API_KEY_PREFIX",
    "STATE_NEEDS_REAUTH",
    "STATE_READY",
    "ApiKeyCredentialSource",
    "Credential",
    "CredentialError",
    "CredentialSource",
    "CredentialState",
    "PkceCredentialSource",
    "looks_like_api_key",
    "mask_secret",
    "AUTHORIZE_PATH",
    "DEFAULT_API_BASE",
    "DEFAULT_AUTH_BASE",
    "EXCHANGE_PATH",
    "authorize_url_base",
    "exchange_url",
    "models_url",
    "resolve_api_base",
    "resolve_auth_base",
    "FLOW_LOOPBACK",
    "FLOW_OOB",
    "PkceAttempt",
    "PkceError",
    "create_attempt",
    "read_granted_scope",
    "states_match",
    "CAPABILITY_CHAT",
    "CAPABILITY_EMBEDDING",
    "CAPABILITY_IMAGE",
    "CAPABILITY_RERANK",
    "CAPABILITY_VIDEO",
    "CatalogResult",
    "Model",
    "SOURCE_LAST_KNOWN_GOOD",
    "SOURCE_LIVE",
    "SOURCE_SEED",
    "VERIFIED_SEED",
    "catalog_from_ids",
    "discover",
    "public_options",
    "resolve_compatible",
    "seed_models",
    "select_for",
    "ConnectError",
    "connect",
    "exchange_code",
    "ENV_API_KEY",
    "SOURCE_API_KEY",
    "SOURCE_PKCE",
    "clear_record",
    "read_record",
    "resolve_api_key",
    "resolve_source_kind",
    "write_record",
]


def resolve_credential(
    generative_config=None,
    *,
    environ=None,
    allow_pkce=False,
    flow=FLOW_OOB,
    opener=None,
    prompt=None,
    announce=None,
):
    """Resolve an OrcaRouter credential through the credential seam.

    A configured key (config or ``ORCAROUTER_API_KEY``) or a key previously
    stored by the connect flow is used directly. When nothing is stored and
    ``allow_pkce`` is set, the connect flow runs and the issued key is
    persisted.
    """
    from seagoat.utils.orcarouter import oauth

    configured = resolve_api_key(generative_config, environ)
    if configured:
        return ApiKeyCredentialSource(
            lambda: configured,
            provenance=resolve_source_kind(generative_config, environ)
            or SOURCE_API_KEY,
        ).resolve()

    if not allow_pkce:
        raise CredentialError(
            "No OrcaRouter API key is configured. Paste one with "
            "`gt orcarouter-login --api-key`, or connect with `gt orcarouter-login`."
        )

    auth_base = resolve_auth_base(generative_config, environ)
    kwargs: dict = {"app_name": "SeaGOAT"}
    if opener is not None:
        kwargs["opener"] = opener
    if prompt is not None:
        kwargs["prompt"] = prompt
    if announce is not None:
        kwargs["announce"] = announce
    payload = oauth.connect(auth_base, flow, **kwargs)
    write_record(
        {
            "api_key": payload["key"],
            "source": SOURCE_PKCE,
            "scope": payload.get("scope"),
            "user_id": payload.get("user_id"),
        }
    )
    return Credential(
        api_key=payload["key"],
        source=SOURCE_PKCE,
        scope=payload.get("scope"),
        account_id=payload.get("user_id"),
    )


def discover_models(
    generative_config=None,
    *,
    environ=None,
    capability=None,
    session=None,
    last_known_good=None,
):
    """Discover the OrcaRouter catalog on the configured inference origin."""
    api_base = resolve_api_base(generative_config, environ)
    api_key = resolve_api_key(generative_config, environ)
    return discover(
        api_base,
        api_key,
        capability=capability,
        session=session,
        last_known_good=last_known_good,
    )


def select_models(models, capability=CAPABILITY_CHAT, modality=None):
    return select_for(models, capability, modality)
