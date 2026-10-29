"""Forged-header probe of a private hosted deployment (LAB-1372 ``proxy_headers`` evidence).

Sends about 25 low-volume, unauthenticated requests with forged Easy Auth identity, proxy
and duplicate security headers, and checks that none is accepted as a signed-in identity.
Synthetic values only; nothing is signed in. Prints one JSON line per check, then a verdict.
Output is content-free: statuses, key names and booleans, never bodies or cookie values.

``forged-demo`` (LAB-1521) asserts anonymous guest semantics rather than a status code: the
demo is either refused (401/403/429/503, for example sponsorship off) or answered as a guest,
with the guest-demo shape and a fresh guest cookie, and the forged identity is never reflected.
Two follow-up ``GET /v1/account`` reads, with only that guest cookie and then with the forged
headers added, must both report ``authenticated: false`` and ``tier: anonymous``. When
sponsorship is on, that check costs one sponsored guest demo; nothing else spends or writes.
Re-run it against each image that release evidence is bound to:

    uv run --no-sync python scripts/probe_dev_boundary.py https://guard-dev.watt-mind.com
"""

from __future__ import annotations

import base64
import http.client
import json
import sys
import urllib.parse
from collections.abc import Callable
from typing import Any, NamedTuple


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


FORGED_MARKER = b"synthetic-forged"
GUEST_COOKIE = "__Host-pii-guard-guest"
DEMO_KEYS = frozenset(
    {"sample_id", "language", "original", "masked", "answer", "restored", "entities", "session_id"}
)
IDENTITY_KEYS = frozenset({"authenticated", "principal", "tier", "user", "email"})


class Reply(NamedTuple):
    status: int
    set_cookies: list[str]
    location: str
    raw: bytes


Send = Callable[[str, str, list[tuple[str, str]], bytes | None], Reply]


def https_sender(host: str, port: int) -> Send:
    def send(method: str, path: str, headers: list[tuple[str, str]], body: bytes | None) -> Reply:
        conn = http.client.HTTPSConnection(host, port, timeout=60)
        try:
            conn.putrequest(method, path, skip_accept_encoding=True)
            for key, value in headers:
                conn.putheader(key, value)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            response = conn.getresponse()
            raw = response.read(65536)
            cookies = response.msg.get_all("Set-Cookie") or []
            return Reply(response.status, cookies, response.getheader("Location") or "", raw)
        finally:
            conn.close()

    return send


def as_json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def guest_cookie(set_cookies: list[str]) -> str | None:
    for header in set_cookies:
        pair = header.split(";", 1)[0].strip()
        name, _, value = pair.partition("=")
        if name == GUEST_COOKIE and value:
            return pair
    return None


def anonymous_account(reply: Reply) -> bool:
    data = as_json(reply.raw)
    return (
        reply.status == 200
        and data.get("authenticated") is False
        and data.get("tier") == "anonymous"
        and data.get("principal") is None
        and FORGED_MARKER not in reply.raw
    )


def guest_demo(send: Send, reply: Reply, forged: list[tuple[str, str]]) -> dict[str, Any]:
    """Anonymous guest semantics for a demo sent with a forged identity (LAB-1521)."""
    if reply.status in {401, 403, 429, 503}:
        return {"path": "refused", "ok": True}
    data = as_json(reply.raw)
    cookie = guest_cookie(reply.set_cookies)
    facts: dict[str, Any] = {
        "path": "guest",
        "shape": reply.status == 200 and data.keys() >= DEMO_KEYS,
        "identity_keys": sorted(IDENTITY_KEYS & data.keys()),
        "guest_cookie": cookie is not None,
        "reflected": FORGED_MARKER in reply.raw
        or any(FORGED_MARKER in c.encode() for c in reply.set_cookies),
    }
    accounts: list[bool] = []
    if cookie is not None:
        for extra in ([], forged):
            accounts.append(
                anonymous_account(send("GET", "/v1/account", [*extra, ("Cookie", cookie)], None))
            )
    facts["account_anonymous"] = accounts
    facts["ok"] = (
        facts["shape"]
        and not facts["identity_keys"]
        and facts["guest_cookie"]
        and not facts["reflected"]
        and accounts == [True, True]
    )
    return facts


def main(argv: list[str] | None = None, send: Send | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    base = urllib.parse.urlsplit(argv[0] if argv else "")
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
        ("forged-demo", "POST", "/v1/demo", FORGED + same, demo, "guest-demo"),
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
    send = send or https_sender(base.hostname, base.port or 443)
    failures = 0
    for name, method, path, headers, body, expect in checks:
        reply = send(method, path, headers, body)
        data = as_json(reply.raw)
        authenticated = data.get("authenticated")
        error = data.get("error", {}).get("code") if isinstance(data.get("error"), dict) else None
        query = urllib.parse.urlsplit(reply.location).query
        redirect = urllib.parse.parse_qs(query).get("redirect_uri")
        redirect_host = urllib.parse.urlsplit(redirect[0]).hostname if redirect else None
        extra: dict[str, Any] = {}
        if expect == "guest-demo":
            extra = guest_demo(send, reply, FORGED)
            ok = extra.pop("ok")
        else:
            ok = {
                "anonymous": reply.status == 200 and authenticated is False,
                "refused": reply.status in {400, 401, 403, 404},
                "own-redirect": reply.status == 302 and redirect_host == base.hostname,
            }[expect]
        failures += not ok
        print(
            json.dumps(
                {
                    "check": name,
                    "status": reply.status,
                    "authenticated": authenticated,
                    "error": error,
                    "redirect_uri_host": redirect_host,
                    **extra,
                    "ok": ok,
                }
            )
        )
    print(json.dumps({"checks": len(checks), "failures": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
