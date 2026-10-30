"""The hosted app's browser security headers (LAB-1460): each one once, from the app.

Fictional data only (ADR 0005).
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from pii_guard.app_bundle import Status, create_bundle_app
from pii_guard.config import Settings
from pii_guard.security_headers import (
    SCALAR_STYLE_HASHES,
    SCALAR_VERSION,
    SecurityHeadersMiddleware,
    content_security_policy,
    inline_hashes,
)

REPO = Path(__file__).resolve().parents[1]

ORIGIN = "https://guard.example"
THEME = (
    '\n      (function () { document.documentElement.classList.toggle("dark", false); })();\n    '
)
STYLE = "#strip{color:#7c2d12}"
INDEX = (
    "<!doctype html><html><head><title>PII Guard</title>"
    f"<script>{THEME}</script><style>{STYLE}</style>"
    '<script type="module" crossorigin src="/assets/app.js"></script>'
    '<link rel="stylesheet" href="/assets/app.css"></head>'
    '<body><div id="root"></div></body></html>'
)
EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "same-origin",
    "cross-origin-opener-policy": "same-origin",
}
NAMES = [*EXPECTED, "content-security-policy", "permissions-policy"]


def _hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def _directives(policy: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in policy.split(";"):
        name, *values = part.split()
        assert name not in out, f"directive {name} repeated"
        out[name] = values
    return out


def hosted_settings() -> Settings:
    return Settings(
        _env_file=None,
        hosted=True,
        hosted_public_origin=ORIGIN,
        hosted_trust_easy_auth=True,
        hosted_single_process=True,
        tenant_key=bytes(range(32)).hex(),
        allowed_hosts=("guard.example",),
        detectors=("rules",),
        ner_fallback="off",
        upstream_api_key="synthetic-sponsored-key",
    )


@pytest.fixture
def ui_dir(tmp_path: Path) -> Path:
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text(INDEX, encoding="utf-8")
    (ui / "assets" / "app.js").write_text("console.log('ui')", encoding="utf-8")
    return ui


@pytest.fixture
def client(ui_dir: Path) -> TestClient:
    app = create_bundle_app(
        Status(upstream="mock", detectors=["rules"]), hosted_settings(), ui_dir=ui_dir
    )
    return TestClient(app, base_url=ORIGIN)


def _assert_header_set(response: object, *, docs: bool = False) -> None:
    headers = response.headers  # type: ignore[attr-defined]
    for name in NAMES:
        assert len(headers.get_list(name)) == 1, f"{name}: {headers.get_list(name)}"
    for name, value in EXPECTED.items():
        assert headers[name] == value
    assert "camera=()" in headers["permissions-policy"]
    assert "microphone=()" in headers["permissions-policy"]
    # The ingress sends HSTS; the app must not repeat it.
    assert "strict-transport-security" not in headers
    csp = _directives(headers["content-security-policy"])
    assert csp["frame-ancestors"] == ["'none'"]
    assert csp["object-src"] == ["'none'"]
    if not docs:
        assert csp["default-src"] == ["'self'"]


def test_policy_hashes_the_inline_script_and_style() -> None:
    scripts, styles = inline_hashes(INDEX)
    assert scripts == [_hash(THEME)]  # the module script has a src: not hashed
    assert styles == [_hash(STYLE)]
    csp = _directives(content_security_policy(INDEX, document=False))
    assert csp["script-src"] == ["'self'", _hash(THEME)]
    assert csp["style-src"] == ["'self'", _hash(STYLE)]
    assert "style-src-attr" not in csp
    assert csp["connect-src"] == ["'self'"]
    assert csp["base-uri"] == ["'none'"]
    assert csp["form-action"] == ["'self'"]
    assert "blob:" in csp["img-src"]  # Images screen previews uploads
    for values in csp.values():
        assert "'unsafe-inline'" not in values
        assert "'unsafe-eval'" not in values
        assert "*" not in values


def test_document_policy_allows_the_api_reference_runtime_styles() -> None:
    # LAB-1588: Scalar's injected <style> elements and markup style attributes, by hash only.
    csp = _directives(content_security_policy(INDEX))
    assert csp["style-src"] == ["'self'", _hash(STYLE), *SCALAR_STYLE_HASHES]
    attr = csp["style-src-attr"]
    assert attr[0] == "'unsafe-hashes'"
    assert _hash("width:30px;height:30px;overflow-y:scroll;") in attr
    assert _hash("--line-count: 13; --line-digits: 2;") in attr
    assert _hash("--line-count: 99; --line-digits: 2;") in attr
    assert all(value.startswith("'sha256-") for value in attr[1:])
    assert csp["script-src"] == ["'self'", _hash(THEME)]
    for values in csp.values():
        assert "'unsafe-inline'" not in values
        assert "'unsafe-eval'" not in values


def test_scalar_hashes_are_pinned_to_the_ui_release() -> None:
    # A Scalar upgrade changes the injected texts: re-run tests/test_csp_api_browser.py.
    package = json.loads((REPO / "ui" / "package.json").read_text("utf-8"))
    assert package["dependencies"]["@scalar/api-reference-react"] == SCALAR_VERSION


def test_the_real_index_theme_script_is_hashed() -> None:
    # ui/index.html as committed: one inline theme script, whatever its build-time text.
    index = (REPO / "ui" / "index.html").read_text("utf-8")
    scripts, styles = inline_hashes(index)
    assert len(scripts) == 1
    assert styles == []


@pytest.mark.parametrize(
    "path",
    ["/", "/index.html", "/traffic", "/assets/app.js", "/healthz", "/v1/traffic", "/nope.txt"],
)
def test_every_hosted_response_carries_each_header_once(client: TestClient, path: str) -> None:
    _assert_header_set(client.get(path))


def test_page_policy_matches_the_served_index(client: TestClient) -> None:
    page = client.get("/")
    assert page.text == INDEX
    assert page.headers["content-security-policy"] == content_security_policy(INDEX)


@pytest.mark.parametrize("path", ["/healthz", "/v1/traffic", "/assets/app.js"])
def test_api_responses_keep_the_short_policy(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.headers["content-security-policy"] == content_security_policy(
        INDEX, document=False
    )


def test_host_check_refusal_carries_the_headers(client: TestClient) -> None:
    refused = client.get("/", headers={"Host": "evil.example"})
    assert refused.status_code == 400
    _assert_header_set(refused)


def test_api_docs_keep_framing_rules_without_the_script_allowlist(client: TestClient) -> None:
    response = client.get("/docs")
    _assert_header_set(response, docs=True)
    assert "script-src" not in response.headers["content-security-policy"]


def test_local_up_is_unchanged_unless_asked(ui_dir: Path) -> None:
    status = Status(upstream="mock", detectors=["rules"])
    local = Settings(
        _env_file=None, tenant_key=bytes(range(32)).hex(), detectors=("rules",), ner_fallback="off"
    )
    plain = TestClient(create_bundle_app(status, local, ui_dir=ui_dir)).get("/")
    assert "content-security-policy" not in plain.headers
    forced = TestClient(create_bundle_app(status, local, ui_dir=ui_dir, security_headers=True)).get(
        "/"
    )
    _assert_header_set(forced)


def test_no_ui_page_style_is_hashed(tmp_path: Path) -> None:
    status = Status(upstream="mock", detectors=["rules"])
    app = create_bundle_app(status, hosted_settings(), ui_dir=tmp_path / "none")
    page = TestClient(app, base_url=ORIGIN).get("/")
    _, styles = inline_hashes(page.text)
    assert styles
    csp = _directives(page.headers["content-security-policy"])
    assert csp["style-src"] == ["'self'", *styles, *SCALAR_STYLE_HASHES]


def test_a_header_the_route_set_is_not_repeated() -> None:
    def framed(_request: object) -> PlainTextResponse:
        return PlainTextResponse(
            "ok", headers={"X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "no-referrer"}
        )

    app = Starlette(routes=[Route("/", framed)])
    app.add_middleware(SecurityHeadersMiddleware)
    response = TestClient(app).get("/")
    assert response.headers.get_list("x-frame-options") == ["SAMEORIGIN"]
    assert response.headers.get_list("referrer-policy") == ["no-referrer"]
    assert len(response.headers.get_list("content-security-policy")) == 1
