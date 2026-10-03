"""Tests for the OrcaRouter provider: origins, PKCE, credentials, catalog."""

import base64
import hashlib
import logging
import stat
from unittest.mock import patch

import pytest
import requests

from seagoat.utils.orcarouter import (
    catalog,
    credentials,
    oauth,
    origins,
    pkce,
    store,
)
from tests.conftest import as_session
from seagoat.utils.orcarouter.catalog import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDING,
    CAPABILITY_IMAGE,
    CAPABILITY_RERANK,
    CAPABILITY_VIDEO,
    SOURCE_LAST_KNOWN_GOOD,
    SOURCE_LIVE,
    SOURCE_SEED,
    CatalogResult,
    Model,
    VERIFIED_SEED,
)

FAKE_KEY = "sk-orca-test-0000000000000000000000000000000"
FAKE_CODE = "fake-one-time-code"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raw=None, chunks=None):
        self.status_code = status_code
        self._payload = payload
        self._raw = raw
        self._chunks = chunks
        self.closed = False

    def json(self):
        if self._raw is not None:
            import json

            return json.loads(self._raw)
        return self._payload

    def iter_content(self, size=65536):
        data = self._raw
        if data is None:
            data = b""
        yield data

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.posts: list = []
        self.gets: list = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def isolated_store(tmp_path):
    """Point the credential store at a temporary directory."""
    path = tmp_path / "config.yml"
    with patch.object(store, "config_file", return_value=path):
        yield path


class TestOrigins:
    def test_public_defaults(self):
        assert origins.resolve_auth_base({}, {}) == "https://www.orcarouter.ai"
        assert origins.resolve_api_base({}, {}) == "https://api.orcarouter.ai/v1"

    def test_auth_and_api_origins_are_distinct(self):
        auth = origins.resolve_auth_base({}, {})
        api = origins.resolve_api_base({}, {})
        assert auth != api
        assert not api.startswith(auth)
        assert not auth.startswith(api)

    def test_exchange_is_not_on_the_relay(self):
        url = origins.exchange_url("https://www.orcarouter.ai")
        assert url == "https://www.orcarouter.ai/api/v1/auth/keys"
        assert "/v1/auth/keys" not in url.replace("/api/v1/auth/keys", "")

    def test_env_overrides_take_precedence(self):
        env = {
            origins._ENV_AUTH: "https://auth.internal.example",
            origins._ENV_API: "https://api.internal.example/v1",
            origins._ENV_SHARED: "https://shared.example",
        }
        assert origins.resolve_auth_base({}, env) == "https://auth.internal.example"
        assert origins.resolve_api_base({}, env) == "https://api.internal.example/v1"

    def test_shared_fallback_used_by_both(self):
        env = {origins._ENV_SHARED: "https://selfhosted.example"}
        assert origins.resolve_auth_base({}, env) == "https://selfhosted.example"
        assert origins.resolve_api_base({}, env) == "https://selfhosted.example"

    def test_config_overrides_take_precedence_over_env(self):
        env = {origins._ENV_SHARED: "https://shared.example"}
        config = {
            "authBaseUrl": "https://auth.config.example",
            "apiBaseUrl": "https://api.config.example/v1",
        }
        assert origins.resolve_auth_base(config, env) == "https://auth.config.example"
        assert origins.resolve_api_base(config, env) == "https://api.config.example/v1"

    def test_http_remote_origin_is_rejected(self):
        with pytest.raises(origins.OriginError):
            origins.validate_origin("http://insecure.example")

    def test_http_loopback_is_allowed(self):
        assert origins.validate_origin("http://127.0.0.1:8080") == (
            "http://127.0.0.1:8080"
        )


class TestPkce:
    def test_verifier_is_fresh_per_attempt(self):
        first = pkce.create_attempt("https://www.orcarouter.ai", "oob")
        second = pkce.create_attempt("https://www.orcarouter.ai", "oob")
        assert first.verifier != second.verifier
        assert first.state != second.state

    def test_challenge_is_unpadded_s256(self):
        attempt = pkce.create_attempt("https://www.orcarouter.ai", "oob")
        expected = (
            base64.urlsafe_b64encode(
                hashlib.sha256(attempt.verifier.encode("ascii")).digest()
            )
            .decode("ascii")
            .rstrip("=")
        )
        assert attempt.code_challenge == expected
        assert "=" not in attempt.code_challenge

    def test_authorize_url_carries_challenge_not_verifier(self):
        attempt = pkce.create_attempt("https://www.orcarouter.ai", "oob")
        assert attempt.authorize_url.startswith("https://www.orcarouter.ai/auth?")
        assert "callback_url=oob" in attempt.authorize_url
        assert "code_challenge_method=S256" in attempt.authorize_url
        assert "app_name=SeaGOAT" in attempt.authorize_url
        assert attempt.verifier not in attempt.authorize_url
        assert attempt.state in attempt.authorize_url

    def test_states_match(self):
        assert pkce.states_match("abc", "abc") is True
        assert pkce.states_match("abc", "abd") is False
        assert pkce.states_match("abc", None) is False
        assert pkce.states_match("abc", "") is False

    def test_granted_scope_is_read_back(self):
        assert pkce.read_granted_scope({"scope": "api"}) == "api"

    def test_scope_downgrade_is_refused(self):
        with pytest.raises(pkce.PkceError, match="granted scope"):
            pkce.read_granted_scope({"scope": "connector"}, requested="api")

    def test_missing_scope_is_refused(self):
        with pytest.raises(pkce.PkceError, match="no scope"):
            pkce.read_granted_scope({})

    def test_missing_key_is_refused(self):
        with pytest.raises(pkce.PkceError, match="no key"):
            pkce.extract_key({})


class TestExchange:
    def test_successful_exchange_posts_to_auth_origin(self):
        session = FakeSession(
            FakeResponse(payload={"key": FAKE_KEY, "scope": "api", "user_id": "42"})
        )
        payload = oauth.exchange_code(
            "https://www.orcarouter.ai",
            {"code": FAKE_CODE, "code_verifier": "v", "code_challenge_method": "S256"},
            session=as_session(session),
        )
        assert payload["key"] == FAKE_KEY
        url, kwargs = session.posts[0]
        assert url == "https://www.orcarouter.ai/api/v1/auth/keys"
        assert kwargs["json"]["code_challenge_method"] == "S256"

    @pytest.mark.parametrize("status", [400, 403])
    def test_rejected_code_is_terminal(self, status):
        session = FakeSession(FakeResponse(status_code=status, payload={}))
        with pytest.raises(oauth.ConnectError, match="rejected"):
            oauth.exchange_code(
                "https://www.orcarouter.ai", {}, session=as_session(session)
            )

    def test_rate_limit_is_explained(self):
        session = FakeSession(FakeResponse(status_code=429, payload={}))
        with pytest.raises(oauth.ConnectError, match="rate-limited"):
            oauth.exchange_code(
                "https://www.orcarouter.ai", {}, session=as_session(session)
            )

    def test_exchange_does_not_leak_verifier(self):
        verifier = "secret-verifier-value"
        session = FakeSession(FakeResponse(status_code=403, payload={}))
        with pytest.raises(oauth.ConnectError) as caught:
            oauth.exchange_code(
                "https://www.orcarouter.ai",
                {"code": FAKE_CODE, "code_verifier": verifier},
                session=as_session(session),
            )
        assert verifier not in str(caught.value)

    def test_network_failure_is_wrapped(self):
        session = FakeSession(error=requests.exceptions.ConnectionError("boom"))
        with pytest.raises(oauth.ConnectError, match="Could not reach"):
            oauth.exchange_code(
                "https://www.orcarouter.ai", {}, session=as_session(session)
            )


class TestOobConnect:
    def test_connect_prints_url_and_persists_nothing_itself(self):
        seen = []
        session = FakeSession(
            FakeResponse(payload={"key": FAKE_KEY, "scope": "api", "user_id": "7"})
        )
        payload = oauth.connect(
            "https://www.orcarouter.ai",
            oauth.FLOW_OOB,
            prompt=lambda _msg: FAKE_CODE,
            opener=lambda _url: True,
            announce=seen.append,
            session=as_session(session),
        )
        assert payload["key"] == FAKE_KEY
        assert any("https://www.orcarouter.ai/auth?" in line for line in seen)

    def test_empty_code_is_rejected(self):
        with pytest.raises(oauth.ConnectError, match="No authorization code"):
            oauth.connect(
                "https://www.orcarouter.ai",
                oauth.FLOW_OOB,
                prompt=lambda _msg: "",
                opener=lambda _url: True,
                announce=lambda _msg: None,
                session=as_session(FakeSession(FakeResponse(payload={}))),
            )

    def test_verifier_never_appears_in_logs(self, caplog):
        session = FakeSession(FakeResponse(status_code=403, payload={}))
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(oauth.ConnectError):
                oauth.connect(
                    "https://www.orcarouter.ai",
                    oauth.FLOW_OOB,
                    prompt=lambda _msg: FAKE_CODE,
                    opener=lambda _url: True,
                    announce=lambda _msg: None,
                    session=as_session(session),
                )
        # The verifier belongs in the exchange body and nowhere else.
        assert session.posts[0][1]["json"]["code_verifier"]
        assert session.posts[0][1]["json"]["code_verifier"] not in caplog.text


class TestLoopbackFlow:
    @staticmethod
    def _callback_url(attempt):
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(attempt.authorize_url).query)
        return query["callback_url"][0]

    def test_loopback_state_mismatch_is_rejected_without_exchange(self, monkeypatch):
        import urllib.request

        session = FakeSession(FakeResponse(payload={"key": FAKE_KEY, "scope": "api"}))
        attempts = {}
        real_create = pkce.create_attempt

        def spy(auth_base, callback_url, app_name=pkce.APP_NAME, scope=pkce.SCOPE_API):
            attempt = real_create(auth_base, callback_url, app_name, scope)
            attempts["attempt"] = attempt
            return attempt

        monkeypatch.setattr(oauth, "create_attempt", spy)

        def opener(_url):
            callback = self._callback_url(attempts["attempt"])
            urllib.request.urlopen(
                f"{callback}?code={FAKE_CODE}&state=wrong-state", timeout=5
            ).read()
            return True

        with pytest.raises(oauth.ConnectError, match="state check"):
            oauth.connect(
                "https://www.orcarouter.ai",
                oauth.FLOW_LOOPBACK,
                opener=opener,
                announce=lambda _msg: None,
                timeout=10,
                session=as_session(session),
            )
        assert session.posts == []

    def test_loopback_success_exchanges_the_code(self, monkeypatch):
        import urllib.request

        session = FakeSession(
            FakeResponse(payload={"key": FAKE_KEY, "scope": "api", "user_id": "9"})
        )
        attempts = {}
        real_create = pkce.create_attempt

        def spy(auth_base, callback_url, app_name=pkce.APP_NAME, scope=pkce.SCOPE_API):
            attempt = real_create(auth_base, callback_url, app_name, scope)
            attempts["attempt"] = attempt
            return attempt

        monkeypatch.setattr(oauth, "create_attempt", spy)

        def opener(_url):
            callback = self._callback_url(attempts["attempt"])
            state = attempts["attempt"].state
            urllib.request.urlopen(
                f"{callback}?code={FAKE_CODE}&state={state}", timeout=5
            ).read()
            return True

        payload = oauth.connect(
            "https://www.orcarouter.ai",
            oauth.FLOW_LOOPBACK,
            opener=opener,
            announce=lambda _msg: None,
            timeout=10,
            session=as_session(session),
        )
        assert payload["key"] == FAKE_KEY
        assert session.posts[0][0] == "https://www.orcarouter.ai/api/v1/auth/keys"
        assert session.posts[0][1]["json"]["code"] == FAKE_CODE

    def test_loopback_timeout_is_terminal(self):
        with pytest.raises(oauth.ConnectError, match="Timed out"):
            oauth.connect(
                "https://www.orcarouter.ai",
                oauth.FLOW_LOOPBACK,
                opener=lambda _url: True,
                announce=lambda _msg: None,
                timeout=0.2,
                session=as_session(FakeSession(FakeResponse(payload={}))),
            )


class TestCredentials:
    def test_api_key_source_accepts_prefixed_key(self):
        source = credentials.ApiKeyCredentialSource(lambda: FAKE_KEY)
        credential = source.resolve()
        assert credential.api_key == FAKE_KEY
        assert credential.source == "api_key"

    def test_api_key_source_rejects_bad_shape(self):
        source = credentials.ApiKeyCredentialSource(lambda: "not-a-key")
        with pytest.raises(credentials.CredentialError, match="does not look like"):
            source.resolve()

    def test_api_key_source_reports_missing_key(self):
        source = credentials.ApiKeyCredentialSource(lambda: None)
        with pytest.raises(credentials.CredentialError, match="No OrcaRouter API key"):
            source.resolve()

    def test_mask_never_reveals_the_middle(self):
        masked = credentials.mask_secret(FAKE_KEY)
        assert FAKE_KEY not in masked
        assert masked.startswith("sk-orca")
        assert masked.endswith(FAKE_KEY[-4:])

    def test_both_adapters_share_one_credential_shape(self):
        api_credential = credentials.ApiKeyCredentialSource(lambda: FAKE_KEY).resolve()
        pkce_credential = credentials.PkceCredentialSource(
            lambda: {"key": FAKE_KEY, "scope": "api", "user_id": "1"}
        ).resolve()
        assert isinstance(api_credential, credentials.Credential)
        assert isinstance(pkce_credential, credentials.Credential)
        assert api_credential.api_key == pkce_credential.api_key
        assert {api_credential.source, pkce_credential.source} == {"api_key", "pkce"}

    def test_credential_redacts_itself(self):
        credential = credentials.ApiKeyCredentialSource(lambda: FAKE_KEY).resolve()
        assert FAKE_KEY not in credential.redacted(f"auth failed for {FAKE_KEY}")

    def test_generation_safe_needs_reauth(self):
        state = credentials.CredentialState()
        first = state.adopt(credentials.Credential(api_key=FAKE_KEY, source="api_key"))
        assert first.generation == 1
        assert state.mark_unauthorized(generation=1) is True
        assert state.needs_reauth is True

        second = state.adopt(credentials.Credential(api_key=FAKE_KEY, source="pkce"))
        assert second.generation == 2
        assert state.needs_reauth is False
        # A late 401 from the old generation must not poison the new one.
        assert state.mark_unauthorized(generation=1) is False
        assert state.needs_reauth is False
        assert state.mark_unauthorized(generation=2) is True


class TestStore:
    def test_round_trip_and_clear(self, isolated_store):
        store.write_record({"api_key": FAKE_KEY, "source": "pkce"})
        assert store.stored_key() == FAKE_KEY
        assert store.read_record()["source"] == "pkce"
        assert store.clear_record() is True
        assert store.stored_key() is None
        assert store.clear_record() is False

    def test_permissions_are_owner_only(self, isolated_store):
        store.write_record({"api_key": FAKE_KEY, "source": "pkce"})
        mode = stat.S_IMODE(isolated_store.stat().st_mode)
        assert mode == 0o600

    def test_resolution_precedence(self, isolated_store):
        store.write_record({"api_key": "sk-orca-stored", "source": "pkce"})
        assert (
            store.resolve_api_key({"apiKey": "sk-orca-config"}, {}) == "sk-orca-config"
        )
        assert (
            store.resolve_api_key({}, {store.ENV_API_KEY: "sk-orca-env"})
            == "sk-orca-env"
        )
        assert store.resolve_api_key({}, {}) == "sk-orca-stored"

    def test_source_kind_reports_provenance_without_the_key(self, isolated_store):
        store.write_record({"api_key": FAKE_KEY, "source": "pkce"})
        assert store.resolve_source_kind({}, {}) == store.SOURCE_PKCE
        assert (
            store.resolve_source_kind({}, {store.ENV_API_KEY: "sk-orca-env"})
            == store.SOURCE_API_KEY
        )


def _model(model_id, endpoints, modalities=None, context=None):
    return Model(
        id=model_id,
        endpoint_types=tuple(endpoints),
        input_modalities=tuple(modalities or ()),
        context_length=context,
    )


class TestCatalogFilters:
    FIXTURES = (
        _model("text/plain-chat", ["openai"], ["text"]),
        _model("multi/vision-chat", ["openai", "anthropic"], ["text", "image"]),
        _model("embed/only", ["embeddings"], ["text"]),
        _model("image/gen", ["image-generation"], ["text"]),
        _model("video/gen", ["openai-video"], ["text"]),
        _model("rerank/only", ["jina-rerank"], ["text"]),
        _model("unknown/route", ["some-unknown-endpoint"], ["text"]),
        _model("undeclared/modalities", ["openai"], []),
    )

    def test_text_chat_excludes_non_text_routes(self):
        ids = [m.id for m in catalog.filter_for_text_chat(self.FIXTURES)]
        assert "text/plain-chat" in ids
        assert "multi/vision-chat" in ids
        assert "unknown/route" not in ids
        assert "image/gen" not in ids
        assert "video/gen" not in ids
        assert "rerank/only" not in ids
        assert "embed/only" not in ids

    def test_multimodal_is_fail_closed(self):
        ids = [
            m.id
            for m in catalog.filter_for_multimodal(
                self.FIXTURES, catalog.MODALITY_IMAGE
            )
        ]
        assert ids == ["multi/vision-chat"]
        assert "undeclared/modalities" not in ids

    def test_capability_selection(self):
        assert [
            m.id for m in catalog.select_for(self.FIXTURES, CAPABILITY_EMBEDDING)
        ] == ["embed/only"]
        assert [m.id for m in catalog.select_for(self.FIXTURES, CAPABILITY_IMAGE)] == [
            "image/gen"
        ]
        assert [m.id for m in catalog.select_for(self.FIXTURES, CAPABILITY_VIDEO)] == [
            "video/gen"
        ]
        assert [m.id for m in catalog.select_for(self.FIXTURES, CAPABILITY_RERANK)] == [
            "rerank/only"
        ]
        assert "image/gen" not in [
            m.id for m in catalog.select_for(self.FIXTURES, CAPABILITY_CHAT)
        ]

    def test_unknown_capability_raises(self):
        with pytest.raises(ValueError):
            catalog.select_for(self.FIXTURES, "teleportation")

    def test_model_ids_keep_their_namespace(self):
        models = catalog.parse_catalog(
            {"data": [{"id": "vendor/model-1", "supported_endpoint_types": ["openai"]}]}
        )
        assert models[0].id == "vendor/model-1"


class TestCatalogParsing:
    def test_metadata_is_preserved(self):
        models = catalog.parse_catalog(
            {
                "data": [
                    {
                        "id": "openai/gpt-5.5",
                        "supported_endpoint_types": ["openai"],
                        "context_length": 400000,
                        "architecture": {"input_modalities": ["text", "image"]},
                        "reasoning": {"efforts": ["low", "medium", "high", "xhigh"]},
                    }
                ]
            }
        )
        model = models[0]
        assert model.context_length == 400000
        assert model.input_modalities == ("text", "image")
        assert model.reasoning_efforts == ("low", "medium", "high", "xhigh")

    def test_malformed_records_are_dropped(self):
        models = catalog.parse_catalog(
            {"data": [{"no_id": True}, {"id": ""}, {"id": "ok/model"}, "junk"]}
        )
        assert [m.id for m in models] == ["ok/model"]

    def test_item_count_is_bounded(self):
        payload = {"data": [{"id": f"m/{i}"} for i in range(50)]}
        assert len(catalog.parse_catalog(payload, max_items=10)) == 10


class TestDiscover:
    def test_live_result_is_authoritative(self):
        payload = b'{"data":[{"id":"live/model","supported_endpoint_types":["openai"],"architecture":{"input_modalities":["text"]}}]}'
        session = FakeSession(FakeResponse(raw=payload))
        result = catalog.discover(
            "https://api.orcarouter.ai/v1", FAKE_KEY, session=as_session(session)
        )
        assert result.source == SOURCE_LIVE
        assert result.degraded is False
        assert result.ids() == ["live/model"]
        # The seed must not be mixed into a successful live result.
        assert "orcarouter/auto" not in result.ids()
        url, kwargs = session.gets[0]
        assert url == "https://api.orcarouter.ai/v1/models"
        assert kwargs["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"

    def test_capability_is_forwarded(self):
        payload = b'{"data":[{"id":"a/b"}]}'
        session = FakeSession(FakeResponse(raw=payload))
        catalog.discover(
            "https://api.orcarouter.ai/v1",
            FAKE_KEY,
            capability=CAPABILITY_CHAT,
            session=as_session(session),
        )
        assert (
            session.gets[0][0] == "https://api.orcarouter.ai/v1/models?capability=chat"
        )

    def test_network_failure_falls_back_to_seed(self):
        session = FakeSession(error=requests.exceptions.ConnectionError("down"))
        result = catalog.discover(
            "https://api.orcarouter.ai/v1", FAKE_KEY, session=as_session(session)
        )
        assert result.degraded is True
        assert result.source == SOURCE_SEED
        assert result.ids() == [m.id for m in VERIFIED_SEED]

    def test_failure_keeps_last_known_good(self):
        session = FakeSession(error=requests.exceptions.ConnectionError("down"))
        previous = [Model(id="cached/model", endpoint_types=("openai",))]
        result = catalog.discover(
            "https://api.orcarouter.ai/v1",
            FAKE_KEY,
            session=as_session(session),
            last_known_good=previous,
        )
        assert result.source == SOURCE_LAST_KNOWN_GOOD
        assert result.ids() == ["cached/model"]

    def test_auth_error_falls_back(self):
        session = FakeSession(FakeResponse(status_code=401))
        result = catalog.discover(
            "https://api.orcarouter.ai/v1", FAKE_KEY, session=as_session(session)
        )
        assert result.degraded is True
        assert result.source == SOURCE_SEED

    def test_seed_retains_reasoning_and_modality_metadata(self):
        gpt = next(m for m in catalog.seed_models() if m.id == "openai/gpt-5.5")
        assert gpt.reasoning_efforts == ("low", "medium", "high", "xhigh")
        assert "image" in gpt.input_modalities

    def test_seed_copies_do_not_share_state(self):
        first = catalog.seed_models()
        first[0].input_modalities = ("text",)
        assert "image" in catalog.seed_models()[0].input_modalities

    def test_oversized_response_is_rejected(self):
        class Huge:
            def __init__(self):
                self.status_code = 200

            def iter_content(self, size):
                for _ in range(64):
                    yield b"x" * (1024 * 1024)

            def close(self):
                pass

        result = catalog.discover(
            "https://api.orcarouter.ai/v1",
            FAKE_KEY,
            session=as_session(FakeSession(Huge())),
        )
        assert result.degraded is True
        assert result.source == SOURCE_SEED


class TestSelectionHelpers:
    def test_incompatible_selection_is_cleared(self):
        models = [
            _model("text/only", ["openai"], ["text"]),
            _model("multi/vision", ["openai"], ["text", "image"]),
        ]
        result = CatalogResult(models=models)
        assert catalog.resolve_compatible(result, "multi/vision") == "multi/vision"
        assert catalog.resolve_compatible(result, "multi/vision", modality="image") == (
            "multi/vision"
        )
        assert catalog.resolve_compatible(result, "text/only", modality="image") is None

    def test_public_options_expose_only_minimal_metadata(self):
        models = [_model("a/b", ["openai"], ["text"], context=123)]
        options = catalog.public_options(CatalogResult(models=models))
        assert options == [
            {
                "id": "a/b",
                "context_length": 123,
                "input_modalities": ["text"],
                "reasoning_efforts": [],
                "supported_endpoint_types": ["openai"],
                "source": SOURCE_LIVE,
            }
        ]

    def test_catalog_from_ids_keeps_verified_metadata(self):
        result = catalog.catalog_from_ids(["openai/gpt-5.5", "unknown/model"])
        by_id = {m.id: m for m in result.models}
        assert by_id["openai/gpt-5.5"].reasoning_efforts == (
            "low",
            "medium",
            "high",
            "xhigh",
        )
        assert by_id["unknown/model"].endpoint_types == ()
