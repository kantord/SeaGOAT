"""End-to-end tests for the OrcaRouter provider wiring.

These tests run a real local HTTP server for each OrcaRouter origin (auth and
inference) and drive the actual provider code path: connect -> persist ->
resolve credential -> discover catalog -> filter options. Nothing is
hardcoded to a model list; the options must come from the served API.
"""

import http.server
import json
import threading
import os
from contextlib import contextmanager
from typing import Callable, cast

import pytest
import requests

from tests.conftest import as_session

from seagoat.utils import orcarouter as orcarouter_pkg
from seagoat.utils.orcarouter import (
    CAPABILITY_CHAT,
    SOURCE_LIVE,
    SOURCE_SEED,
    catalog,
    oauth,
    store,
)
from seagoat.utils.orcarouter.origins import OriginError

FAKE_KEY = "sk-orca-integration-000000000000000000000"
FAKE_CODE = "integration-code"

AUTH_RESPONSE = {"key": FAKE_KEY, "scope": "api", "user_id": "acct-1"}

API_CATALOG = {
    "object": "list",
    "data": [
        {
            "id": "openai/gpt-5.5",
            "supported_endpoint_types": ["openai", "openai-response"],
            "context_length": 400000,
            "architecture": {"input_modalities": ["text", "image"]},
            "reasoning": {"efforts": ["low", "medium", "high", "xhigh"]},
        },
        {
            "id": "deepseek/deepseek-v4-pro",
            "supported_endpoint_types": ["openai"],
            "context_length": 131072,
            "architecture": {"input_modalities": ["text"]},
        },
        {
            "id": "vendor/image-only",
            "supported_endpoint_types": ["image-generation"],
            "architecture": {"input_modalities": ["text"]},
        },
    ],
}


class _TypedServer(http.server.HTTPServer):
    respond: "Callable[..., tuple]"
    requests: "list"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests = []


class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        server = cast(_TypedServer, self.server)
        status, payload = server.respond(self.path, dict(self.headers), body)
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _handle
    do_POST = _handle


@contextmanager
def fake_server(respond):
    server = _TypedServer(("127.0.0.1", 0), _RecordingHandler)
    server.respond = respond
    server.requests = []
    original = server.respond

    def recording(path, headers, body):
        server.requests.append({"path": path, "headers": headers, "body": body})
        return original(path, headers, body)

    server.respond = recording
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def isolated_store(tmp_path):
    from unittest.mock import patch

    path = tmp_path / "config.yml"
    with patch.object(store, "config_file", return_value=path):
        yield path


def _auth_responder(path, _headers, _body):
    if path == "/api/v1/auth/keys":
        return 200, AUTH_RESPONSE
    return 404, {"error": "not_found"}


def _api_responder(path, headers, _body):
    if not path.startswith("/v1/models"):
        return 404, {"error": "not_found", "path": path}
    authorized = bool(headers.get("Authorization"))
    if not authorized:
        return 401, {"error": "missing key"}
    return 200, API_CATALOG


class TestOriginSeparation:
    def test_auth_and_inference_hit_separate_origins(self, isolated_store):
        with (
            fake_server(_auth_responder) as (auth, auth_base),
            fake_server(_api_responder) as (api, api_base),
        ):
            config = {
                "authBaseUrl": auth_base,
                "apiBaseUrl": f"{api_base}/v1",
            }

            # 1. Connect through the PKCE seam against the auth origin.
            payload = oauth.connect(
                orcarouter_pkg.resolve_auth_base(config, {}),
                oauth.FLOW_OOB,
                prompt=lambda _m: FAKE_CODE,
                opener=lambda _u: True,
                announce=lambda _m: None,
            )
            assert payload["key"] == FAKE_KEY

            # 2. Persist exactly as the CLI does.
            store.write_record(
                {"api_key": payload["key"], "source": "pkce", "scope": "api"}
            )

            # 3. Discover through the provider path against the API origin.
            result = orcarouter_pkg.discover_models(config, environ={})
            options = orcarouter_pkg.public_options(result, CAPABILITY_CHAT)

        assert [request["path"] for request in auth.requests] == ["/api/v1/auth/keys"]
        assert result.source == SOURCE_LIVE
        ids = [option["id"] for option in options]
        # Options come from the served API, including its exact namespace.
        assert "deepseek/deepseek-v4-pro" in ids
        assert "vendor/image-only" not in ids

        api_request = api.requests[0]
        assert api_request["path"] == "/v1/models"
        assert api_request["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"

    def test_seed_is_not_mixed_into_live_result(self, isolated_store):
        with (
            fake_server(_auth_responder) as (_auth, auth_base),
            fake_server(_api_responder) as (_api, api_base),
        ):
            config = {
                "apiKey": FAKE_KEY,
                "authBaseUrl": auth_base,
                "apiBaseUrl": f"{api_base}/v1",
            }
            result = orcarouter_pkg.discover_models(config, environ={})

        ids = result.ids()
        assert result.source == SOURCE_LIVE
        assert "orcarouter/auto" not in ids
        assert len(ids) == len(API_CATALOG["data"])

    def test_unauthenticated_catalog_falls_back_to_seed(self, isolated_store):
        with fake_server(_api_responder) as (_api, api_base):
            config = {"apiBaseUrl": f"{api_base}/v1"}
            result = orcarouter_pkg.discover_models(config, environ={})

        assert result.degraded is True
        assert result.source == SOURCE_SEED

    def test_inference_origin_never_receives_the_auth_code(self, isolated_store):
        with (
            fake_server(_auth_responder) as (_auth, auth_base),
            fake_server(_api_responder) as (api, api_base),
        ):
            config = {"authBaseUrl": auth_base, "apiBaseUrl": f"{api_base}/v1"}
            oauth.connect(
                orcarouter_pkg.resolve_auth_base(config, {}),
                oauth.FLOW_OOB,
                prompt=lambda _m: FAKE_CODE,
                opener=lambda _u: True,
                announce=lambda _m: None,
            )
            orcarouter_pkg.discover_models(config, environ={})

        for request in api.requests:
            assert FAKE_CODE not in request["path"]
            assert FAKE_CODE not in (request["headers"].get("Authorization") or "")

    def test_remote_http_origin_is_refused(self, isolated_store):
        with pytest.raises(OriginError):
            orcarouter_pkg.resolve_api_base({"apiBaseUrl": "http://example.com/v1"})


class TestPkceAdapter:
    """The full PKCE adapter: authorize -> exchange -> persist -> reuse."""

    def test_adapter_persists_then_reuses_without_reconnect(self, isolated_store):
        with fake_server(_auth_responder) as (auth, auth_base):
            config = {"authBaseUrl": auth_base}
            credential = orcarouter_pkg.resolve_credential(
                config,
                environ={},
                allow_pkce=True,
                flow=orcarouter_pkg.FLOW_OOB,
                prompt=lambda _m: FAKE_CODE,
                opener=lambda _u: True,
                announce=lambda _m: None,
            )
            assert credential.api_key == FAKE_KEY
            assert credential.source == "pkce"
            assert store.stored_key() == FAKE_KEY
            exchanges_before = len(auth.requests)

            # A second resolution reuses the stored key; no new login.
            reused = orcarouter_pkg.resolve_credential(config, environ={})
            assert reused.api_key == FAKE_KEY
            assert reused.source == "pkce"
            assert len(auth.requests) == exchanges_before

        assert [r["path"] for r in auth.requests] == ["/api/v1/auth/keys"]

    def test_denial_persists_nothing(self, isolated_store):
        def denied(path, _headers, _body):
            return 403, {"error": "access_denied"}

        with fake_server(denied) as (_server, auth_base):
            config = {"authBaseUrl": auth_base}
            with pytest.raises(orcarouter_pkg.ConnectError):
                orcarouter_pkg.resolve_credential(
                    config,
                    environ={},
                    allow_pkce=True,
                    flow=orcarouter_pkg.FLOW_OOB,
                    prompt=lambda _m: FAKE_CODE,
                    opener=lambda _u: True,
                    announce=lambda _m: None,
                )
        assert store.stored_key() is None

    def test_missing_key_without_pkce_is_a_clear_error(self, isolated_store):
        with pytest.raises(orcarouter_pkg.CredentialError, match="No OrcaRouter API"):
            orcarouter_pkg.resolve_credential({}, environ={})


class TestSelectorOptions:
    """The model selector for the OrcaRouter provider."""

    def _catalog(self):
        models = catalog.parse_catalog(API_CATALOG)
        return catalog.CatalogResult(models=models, source=SOURCE_LIVE)

    def test_chat_options_exclude_non_text_routes(self):
        options = catalog.public_options(self._catalog(), CAPABILITY_CHAT)
        ids = [option["id"] for option in options]
        assert ids == ["openai/gpt-5.5", "deepseek/deepseek-v4-pro"]

    def test_image_attachment_narrows_to_declared_modality(self):
        catalog_result = self._catalog()
        text_options = catalog.public_options(catalog_result, CAPABILITY_CHAT)
        image_options = catalog.public_options(
            catalog_result, CAPABILITY_CHAT, modality="image"
        )
        assert [o["id"] for o in image_options] == ["openai/gpt-5.5"]
        assert len(image_options) < len(text_options)

    def test_current_text_model_is_invalidated_on_multimodal_switch(self):
        catalog_result = self._catalog()
        assert (
            catalog.resolve_compatible(catalog_result, "deepseek/deepseek-v4-pro")
            == "deepseek/deepseek-v4-pro"
        )
        # The same selection is no longer compatible once an image is attached.
        assert (
            catalog.resolve_compatible(
                catalog_result, "deepseek/deepseek-v4-pro", modality="image"
            )
            is None
        )

    def test_incompatible_old_value_is_cleared_when_provider_changes(self):
        catalog_result = self._catalog()
        assert catalog.resolve_compatible(catalog_result, "openai/gpt-4o-mini") is None

    def test_declared_capabilities_are_preserved_in_options(self):
        options = catalog.public_options(self._catalog(), CAPABILITY_CHAT)
        gpt = next(o for o in options if o["id"] == "openai/gpt-5.5")
        assert gpt["reasoning_efforts"] == ["low", "medium", "high", "xhigh"]
        assert gpt["input_modalities"] == ["text", "image"]


class TestDegradedSelector:
    def _failing_session(self):
        class Failing:
            def get(self, *args, **kwargs):
                raise requests.exceptions.ConnectionError("catalog offline")

        return as_session(Failing())

    def test_failure_yields_degraded_seed_only(self):
        result = catalog.discover(
            "https://api.orcarouter.ai/v1",
            FAKE_KEY,
            session=self._failing_session(),
        )
        options = catalog.public_options(result, CAPABILITY_CHAT)
        assert result.degraded is True
        assert result.source == SOURCE_SEED
        ids = [option["id"] for option in options]
        assert ids == [
            "openai/gpt-5.5",
            "anthropic/claude-opus-4.8",
            "google/gemini-3.5-flash",
            "deepseek/deepseek-v4-pro",
            "orcarouter/auto",
        ]
        assert "live" not in ids

    def test_degraded_seed_keeps_multimodal_metadata(self):
        result = catalog.discover(
            "https://api.orcarouter.ai/v1",
            FAKE_KEY,
            session=self._failing_session(),
        )
        image_options = catalog.public_options(
            result, CAPABILITY_CHAT, modality="image"
        )
        ids = [option["id"] for option in image_options]
        assert "openai/gpt-5.5" in ids
        assert "deepseek/deepseek-v4-pro" not in ids


@pytest.mark.skipif(
    "ORCAROUTER_API_KEY" not in os.environ,
    reason="live OrcaRouter credential not configured",
)
class TestLiveCatalog:
    """Live checks against the official OrcaRouter origins."""

    def test_live_chat_options_are_real_models(self):
        result = orcarouter_pkg.discover_models(
            {}, environ={"ORCAROUTER_API_KEY": os.environ["ORCAROUTER_API_KEY"]}
        )
        assert result.source == SOURCE_LIVE
        assert result.degraded is False
        options = orcarouter_pkg.public_options(result, CAPABILITY_CHAT)
        assert options, "the live chat catalog must not be empty"
        for option in options:
            assert "/" in option["id"]

    def test_live_auth_origin_is_separate(self):
        assert orcarouter_pkg.resolve_auth_base({}, {}) == ("https://www.orcarouter.ai")
        assert orcarouter_pkg.resolve_api_base({}, {}) == (
            "https://api.orcarouter.ai/v1"
        )

    def test_live_chat_completion_through_the_provider(self):
        from seagoat.utils.llm_provider import stream_chat

        result = orcarouter_pkg.discover_models(
            {}, environ={"ORCAROUTER_API_KEY": os.environ["ORCAROUTER_API_KEY"]}
        )
        options = orcarouter_pkg.public_options(result, CAPABILITY_CHAT)

        # The catalog is authoritative for which models exist; a key may
        # additionally be scoped down, so drive real completions until one of
        # the advertised models actually answers.
        answered = False
        for option in options:
            try:
                chunks = stream_chat(
                    {"generative": {"provider": "orcarouter", "model": option["id"]}},
                    [{"role": "user", "content": "Reply with a single word."}],
                )
                if "".join(chunks).strip():
                    answered = True
                    break
            except Exception:
                continue

        assert answered, "no advertised live chat model produced a completion"
