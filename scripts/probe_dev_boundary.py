"""Forged-header probe of a private hosted deployment (LAB-1372 ``proxy_headers`` evidence).

Sends about 25 low-volume, unauthenticated requests with forged Easy Auth identity, proxy
and duplicate security headers, and checks that none is accepted as a signed-in identity.
Synthetic values only; nothing is signed in. Prints one JSON line per check, then a verdict.
Re-run it against each image that release evidence is bound to:

    uv run --no-sync python scripts/probe_dev_boundary.py https://guard-dev.watt-mind.com
"""

from __future__ import annotations

import base64
import http.client
import json
import sys
import urllib.parse


def principal(subject: str) -> str:
    claims = [
        {"typ": "sub", "val": subject},
        {"typ": "email", "val": f"{subject}@example.com"},
        {
            "typ": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
            "val": subject,
        },
    ]
    return base64.b64encode(json.dumps({"auth_typ": "google", "claims": claims}).encode()).decode()


FORGED = [
    ("X-MS-CLIENT-PRINCIPAL", principal("synthetic-forged")),
    ("X-MS-CLIENT-PRINCIPAL-ID", "synthetic-forged"),
    ("X-MS-CLIENT-PRINCIPAL-NAME", "synthetic-forged@example.com"),
    ("X-MS-CLIENT-PRINCIPAL-IDP", "google"),
    ("X-MS-TOKEN-GOOGLE-ACCESS-TOKEN", "synthetic-forged-access"),
    ("X-MS-TOKEN-GOOGLE-ID-TOKEN", "synthetic-forged-id"),
    ("X-Pii-Guard-External-Host", "evil.example"),
    ("X-Pii-Guard-External-Proto", "http"),
    ("X-Forwarded-Host", "evil.example"),
    ("X-Forwarded-For", "203.0.113.7"),
    ("Forwarded", "for=203.0.113.7;proto=https"),
    ("X-Real-IP", "203.0.113.7"),
    ("X-Original-URL", "/v1/status"),
    ("X-Arr-SSL", "forged"),
]


def main() -> int:
    base = urllib.parse.urlsplit(sys.argv[1] if len(sys.argv) > 1 else "")
    if base.scheme != "https" or not base.hostname:
        print("usage: probe_dev_boundary.py https://<host>", file=sys.stderr)
        return 2
    origin = f"https://{base.netloc}"
    json_type = [("Content-Type", "application/json")]
    same = [("Origin", origin), *json_type]
    mask = b'{"text": "I am Jane Placeholder, jane.placeholder@example.com"}'
    chat = b'{"model": "muse-spark-1.3", "messages": [{"role": "user", "content": "Hello"}]}'
    demo = b'{"sample_id": "en-support"}'
    # (name, method, path, headers, body, what passes)
    checks = [
        ("baseline", "GET", "/v1/account", [], None, "anonymous"),
        ("forged-all", "GET", "/v1/account", FORGED, None, "anonymous"),
        ("forged-principal", "GET", "/v1/account", FORGED[:1], None, "anonymous"),
        ("forged-status", "GET", "/v1/status", FORGED, None, "refused"),
        ("forged-projects", "GET", "/v1/projects", FORGED, None, "refused"),
        ("forged-mask", "POST", "/v1/mask", FORGED + same, mask, "refused"),
        ("forged-keys", "GET", "/v1/account/api-keys", FORGED, None, "refused"),
        (
            "forged-key-create",
            "POST",
            "/v1/account/api-keys",
            FORGED + same,
            b'{"name":"x"}',
            "refused",
        ),
        ("forged-chat", "POST", "/v1/chat/completions", FORGED + same, chat, "refused"),
        ("forged-demo", "POST", "/v1/demo", FORGED + same, demo, "not-signed-in"),
        (
            "forged-guard-key",
            "GET",
            "/v1/status",
            [("Authorization", "Bearer pg_synthetic_forged_0000000000")],
            None,
            "refused",
        ),
        (
            "forged-endpoint-key",
            "GET",
            "/e/synthetic/v1/models",
            [("Authorization", "Bearer pg_ep_synthetic_forged_0000000000")],
            None,
            "refused",
        ),
        (
            "forged-token-header",
            "GET",
            "/v1/status",
            [("X-PII-Guard-Token", "pg_synthetic_forged_0000000000")],
            None,
            "refused",
        ),
        (
            "forged-easy-auth-cookie",
            "GET",
            "/v1/account",
            [("Cookie", "AppServiceAuthSession=synthetic-forged")],
            None,
            "anonymous",
        ),
        (
            "dup-principal",
            "GET",
            "/v1/account",
            [("X-MS-CLIENT-PRINCIPAL", principal("a")), ("X-MS-CLIENT-PRINCIPAL", principal("b"))],
            None,
            "anonymous",
        ),
        (
            "dup-authorization",
            "GET",
            "/v1/status",
            [("Authorization", "Bearer pg_a"), ("Authorization", "Bearer pg_b")],
            None,
            "refused",
        ),
        (
            "dup-origin",
            "POST",
            "/v1/mask",
            [("Origin", origin), ("Origin", "https://evil.example"), *json_type],
            mask,
            "refused",
        ),
        (
            "dup-cookie",
            "GET",
            "/v1/account",
            [("Cookie", "__Host-pii-guard-guest=a"), ("Cookie", "__Host-pii-guard-guest=b")],
            None,
            "anonymous",
        ),
        (
            "dup-token",
            "GET",
            "/v1/status",
            [("X-PII-Guard-Token", "pg_a"), ("X-PII-Guard-Token", "pg_b")],
            None,
            "refused",
        ),
        (
            "cross-origin-demo",
            "POST",
            "/v1/demo",
            [("Origin", "https://evil.example"), *json_type],
            demo,
            "refused",
        ),
        ("login-forged-host", "GET", "/.auth/login/google", FORGED[6:9], None, "own-redirect"),
    ]
    failures = 0
    for name, method, path, headers, body, expect in checks:
        conn = http.client.HTTPSConnection(base.hostname, base.port or 443, timeout=60)
        conn.putrequest(method, path, skip_accept_encoding=True)
        for key, value in headers:
            conn.putheader(key, value)
        if body is not None:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        response = conn.getresponse()
        raw = response.read(65536)
        location = response.getheader("Location") or ""
        conn.close()
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        authenticated = data.get("authenticated") if isinstance(data, dict) else None
        error = data.get("error", {}).get("code") if isinstance(data.get("error"), dict) else None
        redirect = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query).get("redirect_uri")
        redirect_host = urllib.parse.urlsplit(redirect[0]).hostname if redirect else None
        ok = {
            "anonymous": response.status == 200 and authenticated is False,
            "refused": response.status in {400, 401, 403, 404},
            "not-signed-in": response.status in {401, 403, 429, 503},
            "own-redirect": response.status == 302 and redirect_host == base.hostname,
        }[expect]
        failures += not ok
        print(
            json.dumps(
                {
                    "check": name,
                    "status": response.status,
                    "authenticated": authenticated,
                    "error": error,
                    "redirect_uri_host": redirect_host,
                    "ok": ok,
                }
            )
        )
    print(json.dumps({"checks": len(checks), "failures": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
