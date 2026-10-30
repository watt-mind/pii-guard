"""Endpoint-key admission with ``PII_GUARD_API_TOKEN`` set (LAB-1562, LAB-1570).

All keys, models and texts are synthetic; the provider is an ``httpx.MockTransport``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.api.security import BearerTokenMiddleware
from pii_guard.config import Settings
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.rules import RuleDetector
from pii_guard.gateway.config import Mode
from pii_guard.gateway.detection import ModeDetector
from pii_guard.policy import PolicySet

API_TOKEN = "test-api-token-not-a-secret"  # noqa: S105 - fictional
PROVIDER_KEY = "synthetic-provider-secret"
EMAIL = "jane.placeholder@example.com"
OWNER = {"X-PII-Guard-Token": API_TOKEN}


@pytest.fixture
def gateway(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        detectors=("rules",),
        ner_fallback="off",
        tenant_key="38" * 32,
        api_token=API_TOKEN,
        upstream_base_url="https://upstream.invalid/v1",
        project_state_path=str(tmp_path / "state" / "projects.sqlite3"),
    )
    app = create_app(settings)
    sent: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": body["messages"][-1]["content"],
                        },
                    }
                ],
            },
        )

    app.state.gateway_transport = httpx.MockTransport(provider)
    app.state.gateway_detectors = {
        Mode.FAST: ModeDetector(
            Mode.FAST, DetectionPipeline([RuleDetector()]), "rules", PolicySet()
        )
    }
    with TestClient(app) as client:
        project = client.get("/v1/projects", headers=OWNER).json()["projects"][0]
        policy = client.get(f"/v1/projects/{project['id']}/policies", headers=OWNER).json()[
            "policies"
        ][0]
        response = client.post(
            f"/v1/projects/{project['id']}/endpoints",
            headers=OWNER,
            json={
                "name": "Synthetic endpoint",
                "provider": "openai",
                "model": "synthetic-pinned",
                "api_key": PROVIDER_KEY,
                "policy_version_id": policy["policy_version_id"],
            },
        )
        assert response.status_code == 201, response.text
        resource = response.json()
        issued = client.post(
            f"/v1/projects/{project['id']}/endpoints/{resource['id']}/keys",
            headers=OWNER,
            json={"name": "Synthetic client"},
        )
        assert issued.status_code == 201, issued.text
        yield client, resource, issued.json()["key"], sent


def _chat(client: TestClient, resource: dict[str, Any], headers: dict[str, Any]):
    return client.post(
        resource["base_path"] + "/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": EMAIL}]},
    )


def test_valid_endpoint_key_still_works_with_api_token_set(gateway):
    client, resource, key, sent = gateway
    result = _chat(client, resource, {"Authorization": "Bearer " + key})
    assert result.status_code == 200, result.text
    assert len(sent) == 1
    assert sent[0].headers["authorization"] == "Bearer " + PROVIDER_KEY
    assert key not in str(dict(sent[0].headers))


@pytest.mark.parametrize(
    "credential",
    [
        "pg_ep_synthetic-fake",
        "PG_EP_synthetic-fake",
        "Pg_Ep_synthetic-fake",
    ],
)
def test_fake_endpoint_key_is_403_and_never_reaches_the_provider(gateway, credential):
    client, resource, _, sent = gateway
    result = _chat(client, resource, {"Authorization": "Bearer " + credential})
    assert result.status_code == 403, result.text
    assert result.json()["error"]["code"] == "project_access_denied"
    assert not sent
    assert credential not in result.text


def test_cased_prefix_of_the_real_key_is_403(gateway):
    client, resource, key, sent = gateway
    cased = "PG_EP_" + key[len("pg_ep_") :]
    result = _chat(client, resource, {"Authorization": "Bearer " + cased})
    assert result.status_code == 403, result.text
    assert not sent


@pytest.mark.parametrize(
    "headers",
    [
        {"X-PII-Guard-Token": API_TOKEN},
        {"Authorization": "Bearer " + API_TOKEN},
    ],
)
def test_api_token_alone_does_not_load_an_endpoint_snapshot(gateway, headers):
    # With an API token configured, a routed /e/ call must resolve its endpoint
    # snapshot from an endpoint key; the token alone is not endpoint admission.
    client, resource, _, sent = gateway
    result = _chat(client, resource, headers)
    assert result.status_code == 403, result.text
    assert not sent


# --- LAB-1570: the token in any Authorization shape, and endpoint-key edges ------------------


def _plain_chat(client: TestClient, headers: dict[str, Any]):
    return client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "synthetic-byok", "messages": [{"role": "user", "content": "Hi!"}]},
    )


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer\t" + API_TOKEN,
        API_TOKEN,
        "Token " + API_TOKEN,
        "bearer   " + API_TOKEN + "  ",
        b"Bearer\xa0" + API_TOKEN.encode(),  # NBSP as Latin-1
        "Bearer\u2003".encode() + API_TOKEN.encode(),  # EM SPACE as UTF-8
        "Bearer " + API_TOKEN,
    ],
    ids=["tab", "bare", "token-scheme", "padded", "nbsp-latin1", "emsp-utf8", "bearer"],
)
@pytest.mark.parametrize("with_header", [False, True], ids=["alone", "with-x-header"])
def test_api_token_in_any_authorization_shape_is_accepted_and_never_forwarded(
    gateway, authorization, with_header
):
    client, _, _, sent = gateway
    headers = {"Authorization": authorization, **(OWNER if with_header else {})}
    result = _plain_chat(client, headers)
    assert result.status_code == 200, result.text
    assert len(sent) == 1
    assert "authorization" not in sent[0].headers
    assert API_TOKEN not in str(dict(sent[0].headers))
    assert API_TOKEN not in result.text


def test_byok_authorization_is_still_forwarded_with_the_x_header(gateway):
    client, _, _, sent = gateway
    result = _plain_chat(client, {"Authorization": "Bearer client-own-key", **OWNER})
    assert result.status_code == 200, result.text
    assert sent[0].headers["authorization"] == "Bearer client-own-key"


@pytest.mark.parametrize(
    "authorization",
    ["Bearer " + API_TOKEN + "x", "Bearer x" + API_TOKEN, "Bearer " + API_TOKEN[:-1], ""],
)
def test_near_miss_tokens_are_401(gateway, authorization):
    client, _, _, sent = gateway
    result = _plain_chat(client, {"Authorization": authorization})
    assert result.status_code == 401, result.text
    assert not sent
    assert API_TOKEN not in result.text


def test_valid_endpoint_key_with_the_api_token_header_is_403(gateway):
    client, resource, key, sent = gateway
    result = _chat(client, resource, {"Authorization": "Bearer " + key, **OWNER})
    assert result.status_code == 403, result.text
    assert not sent
    assert key not in result.text
    assert API_TOKEN not in result.text


def test_endpoint_key_on_a_non_endpoint_path_is_401(gateway):
    client, _, key, sent = gateway
    result = _plain_chat(client, {"Authorization": "Bearer " + key})
    assert result.status_code == 401, result.text
    assert not sent
    assert key not in result.text


@pytest.mark.parametrize(
    "shape",
    ["BEARER {}", "Bearer   {}", "Bearer {}   ", "bearer  {}\t"],
    ids=["upper-scheme", "lead-pad", "trail-pad", "mixed-pad"],
)
def test_padded_or_cased_endpoint_keys_route_as_endpoint_keys(gateway, shape):
    client, resource, key, sent = gateway
    result = _chat(client, resource, {"Authorization": shape.format(key)})
    assert result.status_code == 200, result.text
    assert sent[0].headers["authorization"] == "Bearer " + PROVIDER_KEY
    assert key not in str(dict(sent[0].headers))


@pytest.mark.parametrize("shape", ["Bearer\t{}", "Bearer\u00a0{}", "Bearer \u2003{}"])
def test_unicode_or_tab_separated_endpoint_keys_fail_closed(gateway, shape):
    client, resource, key, sent = gateway
    result = _chat(client, resource, {"Authorization": shape.format(key).encode()})
    assert result.status_code in {401, 403}, result.text
    assert not sent
    assert key not in result.text


def test_upper_cased_fake_endpoint_key_is_403_not_401(gateway):
    client, resource, _, sent = gateway
    result = _chat(client, resource, {"Authorization": "BEARER PG_EP_synthetic-fake"})
    assert result.status_code == 403, result.text
    assert result.json()["error"]["code"] == "project_access_denied"
    assert not sent


@pytest.mark.parametrize("token", ["", "   "])
def test_empty_api_token_fails_closed(token):
    with pytest.raises(ValueError, match="empty"):
        BearerTokenMiddleware(lambda *_: None, token)  # type: ignore[arg-type]


async def _through_middleware(path: str, headers: list[tuple[bytes, bytes]]):
    seen: list[list[tuple[bytes, bytes]]] = []
    sent: list[dict[str, Any]] = []

    async def inner(scope, receive, send):
        seen.append(list(scope["headers"]))

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": path, "headers": headers}
    await BearerTokenMiddleware(inner, API_TOKEN)(scope, None, send)  # type: ignore[arg-type]
    status = sent[0]["status"] if sent else 200
    return status, (seen[0] if seen else None)


@pytest.mark.parametrize(
    "value",
    [
        b"Bearer\xa0" + API_TOKEN.encode(),  # Latin-1 NBSP, raw on the wire
        b"\xa0" + API_TOKEN.encode() + b"\xa0",
        b"Bearer\t\t" + API_TOKEN.encode(),
        b"Basic " + API_TOKEN.encode(),
    ],
)
def test_raw_latin1_shapes_are_stripped(value):
    import anyio

    raw = [(b"authorization", value), (b"x-pii-guard-token", API_TOKEN.encode())]
    status, seen = anyio.run(_through_middleware, "/v1/chat/completions", raw)
    assert status == 200
    assert seen is not None
    assert all(name != b"authorization" for name, _ in seen)


def test_raw_latin1_padded_endpoint_key_passes_to_project_middleware():
    import anyio

    raw = [(b"authorization", b"Bearer \xa0pg_ep_synthetic-fake\xa0")]
    status, seen = anyio.run(_through_middleware, "/e/synthetic/v1/chat/completions", raw)
    assert status == 200  # admission is ProjectMiddleware's call, not a 401 here
    assert seen == raw


# --- LAB-1462: the Muse Code catalog for an endpoint key ---------------------------------------


def _catalog_ids(result: httpx.Response) -> list[str]:
    assert result.status_code == 200, result.text
    return [m["id"] for m in result.json()["data"]]


@pytest.mark.parametrize("routed", [False, True], ids=["root", "endpoint-path"])
def test_endpoint_key_reads_its_endpoint_muse_catalog(gateway, routed):
    # Muse reads the catalog at the root of its base URL (/muse-code/models), so an endpoint
    # base URL (/e/<id>/v1) sends the endpoint key there: it lists only the pinned model.
    client, resource, key, sent = gateway
    path = f"/e/{resource['id']}/muse-code/models" if routed else "/muse-code/models"
    result = client.get(path, headers={"Authorization": "Bearer " + key})
    assert _catalog_ids(result) == ["synthetic-pinned"]
    assert "muse-code" in result.json()["data"][0]["metadata"]
    assert not sent


def test_fake_endpoint_key_on_the_root_muse_catalog_is_403(gateway):
    client, _, _, sent = gateway
    result = client.get("/muse-code/models", headers={"Authorization": "Bearer pg_ep_fake"})
    assert result.status_code == 403, result.text
    assert not sent


def test_endpoint_key_reaches_no_other_root_route(gateway):
    client, _, key, sent = gateway
    result = client.get("/v1/models", headers={"Authorization": "Bearer " + key})
    assert result.status_code in (401, 403), result.text
    assert not sent


def test_connect_muse_code_catalog_check_works_through_the_endpoint_url(gateway):
    # What `pii-guard connect muse-code --check` (and Muse) read for an endpoint base URL.
    from pii_guard.integrations import muse_code

    client, resource, key, _ = gateway
    base = "http://127.0.0.1:8787" + resource["base_path"]  # the loopback host it allows
    assert muse_code.fetch_catalog(base, token=key, client=client) == ["synthetic-pinned"]


def test_endpoint_snippet_offers_muse_code():
    from pii_guard.integrations import snippets

    built = snippets.build_endpoint(
        gateway_url="https://guard.example/e/ep-synthetic/v1",
        endpoint="ep-synthetic",
        name="Synthetic endpoint",
        model="synthetic-pinned",
        preset=None,
    )
    muse = next(t for t in built["tools"] if t["id"] == "muse-code")
    assert muse["supported"] is True
    assert (
        "pii-guard connect muse-code --gateway https://guard.example/e/ep-synthetic/v1"
        in (muse["code"])
    )
    assert 'META_API_KEY="$PII_GUARD_ENDPOINT_KEY" muse' in muse["code"]


def test_revoked_endpoint_key_on_the_root_muse_catalog_is_403(gateway):
    client, resource, key, sent = gateway
    base = f"/v1/projects/{resource['project_id']}/endpoints/{resource['id']}/keys"
    assert client.get("/muse-code/models", headers={"Authorization": "Bearer " + key}).is_success
    for item in client.get(base, headers=OWNER).json()["keys"]:
        assert client.delete(f"{base}/{item['id']}", headers=OWNER).status_code == 204
    result = client.get("/muse-code/models", headers={"Authorization": "Bearer " + key})
    assert result.status_code == 403, result.text
    assert key not in result.text
    assert not sent


def test_endpoint_key_with_the_api_token_header_on_the_root_catalog_matches_the_endpoint(
    gateway,
):
    client, resource, key, sent = gateway
    headers = {"Authorization": "Bearer " + key, **OWNER}
    root = client.get("/muse-code/models", headers=headers)
    routed = client.get(f"/e/{resource['id']}/muse-code/models", headers=headers)
    assert root.status_code == routed.status_code == 403, (root.text, routed.text)
    assert key not in root.text
    assert API_TOKEN not in root.text
    assert not sent


@pytest.mark.parametrize("path", ["//muse-code/models", "/muse-code/models/"])
def test_endpoint_key_on_a_near_miss_muse_catalog_path_is_refused(gateway, path):
    client, _, key, sent = gateway
    result = client.get(path, headers={"Authorization": "Bearer " + key})
    assert result.status_code in (401, 403, 404), result.text
    assert "synthetic-pinned" not in result.text
    assert not sent


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/models"),
        ("POST", "/v1/chat/completions"),
        ("POST", "/v1/responses"),
        ("GET", "/v1/projects"),
        ("GET", "/v1/sessions"),
    ],
)
def test_api_token_mode_endpoint_key_reaches_only_the_muse_catalog_at_root(gateway, method, path):
    # With PII_GUARD_API_TOKEN set, a pg_ep_ key is not the token: at the root it opens only
    # /muse-code/models (LAB-1462), never another route.
    client, _, key, sent = gateway
    body = {"model": "synthetic-pinned", "messages": [{"role": "user", "content": EMAIL}]}
    result = client.request(
        method,
        path,
        headers={"Authorization": "Bearer " + key},
        json=body if method == "POST" else None,
    )
    assert result.status_code in (401, 403), result.text
    assert key not in result.text
    assert not sent
    assert client.get("/muse-code/models", headers={"Authorization": "Bearer " + key}).is_success


# --- LAB-1591: the token inside a Basic credential or joined by punctuation ------------------


def _basic(credential: str, *, urlsafe: bool = False) -> str:
    encode = base64.urlsafe_b64encode if urlsafe else base64.b64encode
    return encode(credential.encode()).decode()


@pytest.mark.parametrize(
    "authorization",
    [
        "Basic " + _basic("user:" + API_TOKEN),
        "Basic " + _basic(API_TOKEN + ":"),
        "Basic " + _basic(API_TOKEN + ":x"),
        "basic " + _basic("user:" + API_TOKEN).rstrip("="),  # unpadded
        "Basic " + _basic("user:" + API_TOKEN, urlsafe=True),
        _basic("user:" + API_TOKEN),  # no scheme
        b"Basic\xa0" + _basic(API_TOKEN + ":").encode(),  # NBSP as Latin-1
        "Bearer key:" + API_TOKEN,
        "Bearer " + API_TOKEN + ",x",
        'Bearer "' + API_TOKEN + '"',
        "token=" + API_TOKEN,
        "Bearer sk-" + API_TOKEN,
    ],
    ids=[
        "basic-user-token",
        "basic-token-colon",
        "basic-token-password",
        "basic-unpadded",
        "basic-urlsafe",
        "basic-no-scheme",
        "basic-nbsp",
        "colon-joined",
        "comma-joined",
        "quoted",
        "key-equals",
        "dash-joined",
    ],
)
@pytest.mark.parametrize("with_header", [False, True], ids=["alone", "with-x-header"])
def test_encoded_or_punctuation_joined_token_is_accepted_and_never_forwarded(
    gateway, authorization, with_header
):
    # Stripped in every shape; only exact field equality authenticates, so alone it is 401.
    client, _, _, sent = gateway
    headers = {"Authorization": authorization, **(OWNER if with_header else {})}
    result = _plain_chat(client, headers)
    if not with_header:
        assert result.status_code == 401, result.text
        assert not sent
        assert API_TOKEN not in result.text
        return
    assert result.status_code == 200, result.text
    assert len(sent) == 1
    assert "authorization" not in sent[0].headers
    assert API_TOKEN not in str(dict(sent[0].headers))
    assert API_TOKEN not in result.text


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer " + API_TOKEN + "x",
        "Bearer x" + API_TOKEN,
        "Basic " + _basic("user:" + API_TOKEN + "x"),
    ],
    ids=["suffix-glued", "prefix-glued", "basic-glued"],
)
def test_glued_token_does_not_authenticate_but_is_never_forwarded(gateway, authorization):
    # A token glued to letters or digits is no credential, yet its bytes still must not
    # reach the provider: stripped (fail closed), the X header authenticates the call.
    client, _, _, sent = gateway
    assert _plain_chat(client, {"Authorization": authorization}).status_code == 401
    assert not sent
    result = _plain_chat(client, {"Authorization": authorization, **OWNER})
    assert result.status_code == 200, result.text
    assert "authorization" not in sent[0].headers
    assert API_TOKEN not in str(dict(sent[0].headers))


@pytest.mark.parametrize(
    "authorization",
    [
        "Basic " + _basic("user:client-own-password"),
        "Basic " + _basic("user:" + API_TOKEN[:-1]),
        "Basic " + _basic(API_TOKEN[1:] + ":"),
        "Bearer key:" + API_TOKEN[:12],
        "Bearer sk-" + API_TOKEN[:-1],
        'Bearer "' + API_TOKEN[4:] + '"',
        "Bearer " + _basic(API_TOKEN)[:-4],
    ],
    ids=[
        "basic-other",
        "basic-truncated",
        "basic-shifted",
        "colon-prefix-run",
        "dash-truncated",
        "quoted-suffix-run",
        "partial-base64",
    ],
)
def test_byok_credentials_resembling_the_token_are_forwarded_untouched(gateway, authorization):
    client, _, _, sent = gateway
    assert _plain_chat(client, {"Authorization": authorization}).status_code == 401
    assert not sent
    result = _plain_chat(client, {"Authorization": authorization, **OWNER})
    assert result.status_code == 200, result.text
    assert sent[0].headers["authorization"] == authorization


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (b"Bearer " + API_TOKEN.encode(), (True, True)),
        (b"Basic " + _basic("u:" + API_TOKEN).encode(), (True, False)),
        (b"k:" + API_TOKEN.encode(), (True, False)),
        (API_TOKEN.encode() + b"9", (True, False)),
        (b"Basic " + _basic("u:other").encode(), (False, False)),
        (b"Basic !!not-base64!!", (False, False)),
        (b"", (False, False)),
    ],
    ids=["bearer", "basic", "colon", "glued", "basic-other", "invalid-base64", "empty"],
)
def test_carries_token_reports_strip_and_authenticate(value, expected):
    middleware = BearerTokenMiddleware(lambda *_: None, API_TOKEN)  # type: ignore[arg-type]
    assert middleware._carries_token(value) == expected


@pytest.mark.parametrize(
    ("value", "stripped"),
    [
        (b"key:" + API_TOKEN.encode(), True),
        (base64.b64encode(API_TOKEN.encode() + b":"), True),
        (b"sk-ant-" + API_TOKEN.encode()[:-1], False),
    ],
    ids=["colon-joined", "base64", "byok-resembling"],
)
def test_x_api_key_follows_the_same_shapes(value, stripped):
    # Same discipline as Authorization: /v1/messages forwards x-api-key as a BYOK (LAB-1605).
    import anyio

    raw = [(b"x-api-key", value), (b"x-pii-guard-token", API_TOKEN.encode())]
    status, seen = anyio.run(_through_middleware, "/v1/messages", raw)
    assert status == 200
    assert seen is not None
    assert ((b"x-api-key", value) not in seen) is stripped


@pytest.mark.parametrize("value_first", [False, True], ids=["token-first", "oversized-first"])
def test_credential_headers_past_the_scan_cap_are_stripped_unauthenticated(value_first):
    import anyio

    oversized = (b"authorization", b"Bearer " + API_TOKEN.encode() + b" " + b"0" * 9000)
    bearer = (b"x-api-key", API_TOKEN.encode())
    # Alone, an oversized header never authenticates, even with the token as a field.
    status, seen = anyio.run(_through_middleware, "/v1/chat/completions", [oversized])
    assert status == 401
    assert seen is None
    # With the X header: stripped unscanned. Past the cap, later headers are stripped too.
    raw = [oversized, bearer] if value_first else [bearer, oversized]
    raw.append((b"x-pii-guard-token", API_TOKEN.encode()))
    status, seen = anyio.run(_through_middleware, "/v1/chat/completions", raw)
    assert status == 200
    assert seen is not None
    assert all(name not in (b"authorization", b"x-api-key") for name, _ in seen)


def test_byok_header_after_the_cap_is_stripped():
    import anyio

    raw = [
        (b"authorization", b"Bearer " + b"0" * 9000),
        (b"x-api-key", b"sk-client-own-key"),
        (b"x-pii-guard-token", API_TOKEN.encode()),
    ]
    status, seen = anyio.run(_through_middleware, "/v1/messages", raw)
    assert status == 200
    assert seen is not None
    assert all(name not in (b"authorization", b"x-api-key") for name, _ in seen)
