"""OrcaRouter model catalog.

The authoritative model list is ``GET <api base>/models`` on the configured
inference origin. Live discovery is bounded and, when it succeeds, replaces
the small verified seed entirely. When it fails, the verified seed (or a
last-known-good catalog) is used and the result is marked ``degraded`` so the
caller can surface it.

Model IDs keep their ``vendor/model`` namespace verbatim.
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional, Sequence

import requests

from seagoat.utils.orcarouter.origins import models_url

CATALOG_TIMEOUT = 15.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 500

CAPABILITY_CHAT = "chat"
CAPABILITY_EMBEDDING = "embedding"
CAPABILITY_IMAGE = "image"
CAPABILITY_VIDEO = "video"
CAPABILITY_RERANK = "rerank"

CAPABILITIES = (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDING,
    CAPABILITY_IMAGE,
    CAPABILITY_VIDEO,
    CAPABILITY_RERANK,
)

# Endpoint types this client can actually speak for text chat. A record that
# exposes none of these is routed somewhere we cannot call.
CHAT_ENDPOINT_TYPES = {"openai", "anthropic", "gemini", "openai-response"}

# Non-text-specialised routes that must never appear in a text-chat list.
NON_TEXT_ENDPOINT_TYPES = {"image-generation", "openai-video", "jina-rerank"}
EMBEDDING_ENDPOINT_TYPES = {"embeddings"}
IMAGE_ENDPOINT_TYPES = {"image-generation"}
VIDEO_ENDPOINT_TYPES = {"openai-video"}
RERANK_ENDPOINT_TYPES = {"jina-rerank"}

SOURCE_LIVE = "live"
SOURCE_SEED = "seed"
SOURCE_LAST_KNOWN_GOOD = "last_known_good"

MODALITY_TEXT = "text"
MODALITY_IMAGE = "image"
MODALITY_AUDIO = "audio"
MODALITY_VIDEO = "video"


@dataclass
class Model:
    """One catalog entry, keyed by its verbatim OrcaRouter model ID."""

    id: str
    endpoint_types: tuple = ()
    input_modalities: tuple = ()
    context_length: Optional[int] = None
    reasoning_efforts: tuple = ()
    source: str = SOURCE_LIVE
    metadata_verified: bool = False

    def supports_chat(self) -> bool:
        endpoints = set(self.endpoint_types)
        if endpoints & NON_TEXT_ENDPOINT_TYPES:
            return False
        return bool(endpoints & CHAT_ENDPOINT_TYPES)

    def supports_modality(self, modality: str) -> bool:
        """Fail closed: an absent modality list never grants multimodal use."""
        if modality == MODALITY_TEXT:
            return True
        return modality in self.input_modalities

    def supports_endpoint_type(self, endpoint_type: str) -> bool:
        return endpoint_type in set(self.endpoint_types)

    def to_public_dict(self) -> dict:
        """Minimal metadata safe to hand to a caller that holds no key."""
        return {
            "id": self.id,
            "context_length": self.context_length,
            "input_modalities": list(self.input_modalities),
            "reasoning_efforts": list(self.reasoning_efforts),
            "supported_endpoint_types": list(self.endpoint_types),
            "source": self.source,
        }


@dataclass
class CatalogResult:
    models: list = field(default_factory=list)
    source: str = SOURCE_LIVE
    degraded: bool = False
    error: Optional[str] = None
    capabilities: tuple = ()

    def ids(self) -> list:
        return [model.id for model in self.models]


# A small, verified cold-start catalog. It exists so a fresh install is
# usable while `/v1/models` is unreachable; it is never mixed into a
# successful live result.
VERIFIED_SEED = (
    Model(
        id="openai/gpt-5.5",
        endpoint_types=("openai", "openai-response", "anthropic", "gemini"),
        input_modalities=("text", "image"),
        reasoning_efforts=("low", "medium", "high", "xhigh"),
        source=SOURCE_SEED,
        metadata_verified=True,
    ),
    Model(
        id="anthropic/claude-opus-4.8",
        endpoint_types=("anthropic", "openai", "openai-response", "gemini"),
        input_modalities=("text", "image"),
        source=SOURCE_SEED,
        metadata_verified=True,
    ),
    Model(
        id="google/gemini-3.5-flash",
        endpoint_types=("gemini", "openai", "anthropic", "openai-response"),
        input_modalities=("text", "image", "audio", "video"),
        source=SOURCE_SEED,
        metadata_verified=True,
    ),
    Model(
        id="deepseek/deepseek-v4-pro",
        endpoint_types=("openai", "openai-response", "anthropic"),
        input_modalities=("text",),
        source=SOURCE_SEED,
        metadata_verified=True,
    ),
    Model(
        id="orcarouter/auto",
        endpoint_types=("openai", "openai-response", "anthropic", "gemini"),
        input_modalities=("text",),
        source=SOURCE_SEED,
        metadata_verified=True,
    ),
)


def seed_models() -> list:
    """Return copies of the verified seed so callers cannot mutate it."""
    return [
        Model(
            id=model.id,
            endpoint_types=tuple(model.endpoint_types),
            input_modalities=tuple(model.input_modalities),
            context_length=model.context_length,
            reasoning_efforts=tuple(model.reasoning_efforts),
            source=model.source,
            metadata_verified=model.metadata_verified,
        )
        for model in VERIFIED_SEED
    ]


def _as_tuple(value) -> tuple:
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def parse_record(record: Mapping) -> Optional[Model]:
    """Parse one catalog record, rejecting anything with an unusable shape."""
    if not isinstance(record, Mapping):
        return None
    model_id = record.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    architecture = record.get("architecture")
    modalities = ()
    if isinstance(architecture, Mapping):
        modalities = _as_tuple(architecture.get("input_modalities"))
    context_length = record.get("context_length")
    if not isinstance(context_length, int):
        context_length = None
    reasoning = record.get("reasoning")
    efforts = ()
    if isinstance(reasoning, Mapping):
        efforts = _as_tuple(reasoning.get("efforts"))
    return Model(
        id=model_id,
        endpoint_types=_as_tuple(record.get("supported_endpoint_types")),
        input_modalities=modalities,
        context_length=context_length,
        reasoning_efforts=efforts,
        source=SOURCE_LIVE,
    )


def parse_catalog(payload, max_items: int = MAX_ITEMS) -> list:
    """Parse an OpenAI-shaped ``{"data": [...]}`` model list, bounded."""
    if isinstance(payload, Mapping):
        records: Iterable = payload.get("data") or []
    elif isinstance(payload, list):
        records = payload
    else:
        return []
    models = []
    for record in records:
        if len(models) >= max_items:
            break
        model = parse_record(record)
        if model is not None:
            models.append(model)
    return models


def filter_for_text_chat(models: Iterable[Model]) -> list:
    return [model for model in models if model.supports_chat()]


def filter_for_multimodal(models: Iterable[Model], modality: str) -> list:
    """Text-chat models that explicitly declare the uploaded modality."""
    return [
        model
        for model in models
        if model.supports_chat() and model.supports_modality(modality)
    ]


def filter_for_endpoint(models: Iterable[Model], endpoint_types: set) -> list:
    return [model for model in models if set(model.endpoint_types) & endpoint_types]


def select_for(
    models: Iterable[Model],
    capability: str = CAPABILITY_CHAT,
    modality: Optional[str] = None,
) -> list:
    """The single capability gate every AI entry point routes through."""
    if capability == CAPABILITY_CHAT:
        chat = filter_for_text_chat(models)
        if modality and modality != MODALITY_TEXT:
            return filter_for_multimodal(chat, modality)
        return chat
    if capability == CAPABILITY_EMBEDDING:
        return filter_for_endpoint(models, EMBEDDING_ENDPOINT_TYPES)
    if capability == CAPABILITY_IMAGE:
        return filter_for_endpoint(models, IMAGE_ENDPOINT_TYPES)
    if capability == CAPABILITY_VIDEO:
        return filter_for_endpoint(models, VIDEO_ENDPOINT_TYPES)
    if capability == CAPABILITY_RERANK:
        return filter_for_endpoint(models, RERANK_ENDPOINT_TYPES)

    raise ValueError(f"Unknown OrcaRouter capability: {capability}")


def discover(
    api_base: str,
    api_key: Optional[str],
    *,
    capability: Optional[str] = None,
    timeout: float = CATALOG_TIMEOUT,
    session: Optional[requests.Session] = None,
    last_known_good: Optional[Sequence[Model]] = None,
) -> CatalogResult:
    """Fetch the live catalog, falling back to a verified offline list.

    When the request succeeds its records are authoritative; the seed is not
    merged in. When it fails, the caller gets an explicitly ``degraded``
    result built from ``last_known_good`` or the verified seed.
    """
    sender = session or requests
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = sender.get(
            models_url(api_base, capability),
            headers=headers,
            timeout=timeout,
            stream=True,
        )
    except requests.exceptions.RequestException as error:
        return _degraded(last_known_good, _describe(error))

    try:
        if response.status_code != 200:
            return _degraded(
                last_known_good,
                f"model discovery returned HTTP {response.status_code}",
            )
        raw = _read_bounded(response)
    except requests.exceptions.RequestException as error:
        return _degraded(last_known_good, _describe(error))
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()

    try:
        payload = json.loads(raw)
    except ValueError:
        return _degraded(last_known_good, "model discovery returned invalid JSON")

    models = parse_catalog(payload)
    if not models:
        return _degraded(last_known_good, "model discovery returned no usable models")
    return CatalogResult(models=models, source=SOURCE_LIVE)


def _read_bounded(response) -> bytes:
    chunks = []
    total = 0
    for chunk in response.iter_content(64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise requests.exceptions.RequestException(
                "model catalog response exceeded the size limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _describe(error: Exception) -> str:
    return f"model discovery failed: {type(error).__name__}"


def _degraded(last_known_good: Optional[Sequence[Model]], reason: str) -> CatalogResult:
    if last_known_good:
        models = [
            Model(
                id=model.id,
                endpoint_types=tuple(model.endpoint_types),
                input_modalities=tuple(model.input_modalities),
                context_length=model.context_length,
                reasoning_efforts=tuple(model.reasoning_efforts),
                source=SOURCE_LAST_KNOWN_GOOD,
            )
            for model in last_known_good
        ]
        return CatalogResult(
            models=models,
            source=SOURCE_LAST_KNOWN_GOOD,
            degraded=True,
            error=reason,
        )
    return CatalogResult(
        models=seed_models(),
        source=SOURCE_SEED,
        degraded=True,
        error=reason,
    )


def resolve_compatible(
    catalog: CatalogResult,
    selected: Optional[str],
    capability: str = CAPABILITY_CHAT,
    modality: Optional[str] = None,
) -> Optional[str]:
    """Keep ``selected`` only if it survives the current capability filter.

    A value that is no longer compatible must be cleared by the caller, not
    silently sent to the API.
    """
    if not selected:
        return None
    compatible = select_for(catalog.models, capability, modality)
    ids = {model.id for model in compatible}
    return selected if selected in ids else None


def public_options(
    catalog: CatalogResult,
    capability: str = CAPABILITY_CHAT,
    modality: Optional[str] = None,
) -> list:
    """Selector options for one entry point, safe to expose without a key."""
    return [
        model.to_public_dict()
        for model in select_for(catalog.models, capability, modality)
    ]


def catalog_from_ids(ids: Sequence[str], source: str = SOURCE_SEED) -> CatalogResult:
    """Build a catalog from explicit IDs, keeping verified metadata if known."""
    known = {model.id: model for model in VERIFIED_SEED}
    models = []
    for model_id in ids:
        template = known.get(model_id)
        if template is None:
            models.append(Model(id=model_id, source=source))
        else:
            models.append(
                Model(
                    id=template.id,
                    endpoint_types=tuple(template.endpoint_types),
                    input_modalities=tuple(template.input_modalities),
                    reasoning_efforts=tuple(template.reasoning_efforts),
                    source=source,
                )
            )
    return CatalogResult(models=models, source=source)


GetModels = Callable[..., CatalogResult]
