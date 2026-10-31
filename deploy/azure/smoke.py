"""Post-deployment hosted smoke: readiness, security/auth boundaries, and E2E round-trip."""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import re
import sys
import time
from urllib.parse import SplitResult, urlsplit

#: Seconds to wait for the NER model after the revision is Ready (it loads in ~30 s).
READY_WAIT_SECONDS = 180
INDEXED_HOST = "guard.watt-mind.com"
PLACEHOLDER_RE = re.compile(r"\[\[([A-Z_]+)_[a-f0-9]+\]\]")
REQUIRED_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "same-origin",
    "cross-origin-opener-policy": "same-origin",
}
SPOOFED_PRINCIPAL = base64.b64encode(
    json.dumps(
        {
            "auth_typ": "google",
            "claims": [{"typ": "sub", "val": "synthetic-spoof-probe"}],
        }
    ).encode("utf-8")
).decode("ascii")


def _parse_origin(raw: str) -> tuple[SplitResult, str]:
    origin = urlsplit(raw)
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        raise SystemExit("A canonical HTTPS origin is required")
    port = f":{origin.port}" if origin.port and origin.port != 443 else ""
    return origin, f"https://{origin.hostname}{port}"


def _parse_endpoint_path(raw: str, canonical_origin: str) -> str:
    if not raw:
        return "/v1"
    if raw.startswith("/"):
        path = raw.rstrip("/")
    else:
        parsed = urlsplit(raw)
        port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
        if f"{parsed.scheme}://{parsed.hostname}{port}" != canonical_origin:
            raise SystemExit("Endpoint URL must share the canonical HTTPS origin")
        path = parsed.path.rstrip("/")
    if not (path == "/v1" or (path.startswith("/e/") and path.endswith("/v1"))):
        raise SystemExit("Endpoint path must be /v1 or /e/<endpoint_id>/v1")
    return path


def _response_headers(response: http.client.HTTPResponse) -> list[tuple[str, str]]:
    getheaders = getattr(response, "getheaders", None)
    if callable(getheaders):
        pairs = getheaders()
        if isinstance(pairs, list):
            return [(str(k).lower(), str(v)) for k, v in pairs]
    headers = getattr(response, "headers", None)
    if isinstance(headers, list):
        return [(str(k).lower(), str(v)) for k, v in headers]
    if hasattr(headers, "items"):
        items = headers.items()
        if isinstance(items, list) or hasattr(items, "__iter__"):
            return [(str(k).lower(), str(v)) for k, v in items]
    return []


def _check_security_headers(headers: list[tuple[str, str]]) -> None:
    if not headers:
        raise SystemExit("public landing missing security headers")
    by_name: dict[str, list[str]] = {}
    for name, value in headers:
        by_name.setdefault(name, []).append(value)
    for name, expected in REQUIRED_SECURITY_HEADERS.items():
        values = by_name.get(name, [])
        if len(values) != 1 or values[0] != expected:
            raise SystemExit(f"security header {name} missing, duplicated or invalid")
    for name, required_part in (
        ("content-security-policy", "default-src 'self'"),
        ("permissions-policy", "camera=()"),
    ):
        values = by_name.get(name, [])
        if len(values) != 1 or required_part not in values[0]:
            raise SystemExit(f"security header {name} missing, duplicated or invalid")


def _check_robots(connection: http.client.HTTPSConnection, hostname: str) -> None:
    connection.request("GET", "/robots.txt")
    response = connection.getresponse()
    body = response.read().decode("utf-8", errors="replace")
    if response.status != 200:
        raise SystemExit("robots.txt check failed")
    if hostname.lower() == INDEXED_HOST:
        if "Allow: /" not in body or "Disallow: /v1/" not in body:
            raise SystemExit("production robots.txt policy is invalid")
    elif "Disallow: /" not in body or "Allow: /" in body:
        raise SystemExit("non-production robots.txt must disallow indexing")


def _extract_guest_cookie(headers: list[tuple[str, str]]) -> str | None:
    for name, value in headers:
        if name == "set-cookie" and value.startswith("__Host-pii-guard-guest="):
            return value.split(";", 1)[0]
    return None


def _check_demo_roundtrip(payload: dict) -> None:
    masked = payload.get("masked")
    answer = payload.get("answer")
    restored = payload.get("restored")
    entities = payload.get("entities")
    if (
        not isinstance(masked, str)
        or not masked.strip()
        or not isinstance(answer, str)
        or not answer.strip()
        or not isinstance(restored, str)
        or not restored.strip()
    ):
        raise SystemExit("demo E2E returned an empty or invalid payload")
    if "Jane Placeholder" in masked or "jane.placeholder@example.com" in masked:
        raise SystemExit("demo E2E leaked synthetic PII in masked prompt")
    found_types = {match.group(1) for match in PLACEHOLDER_RE.finditer(masked)}
    if not {"PERSON", "EMAIL"} <= found_types:
        raise SystemExit("demo E2E did not mask both PERSON (NER) and EMAIL (rules)")
    if not isinstance(entities, list) or not {"PERSON", "EMAIL"} <= {
        item.get("type") for item in entities if isinstance(item, dict)
    }:
        raise SystemExit("demo E2E returned incomplete entity offsets")
    if PLACEHOLDER_RE.search(restored):
        raise SystemExit("demo E2E left un-restored placeholders in restored answer")


def _tamper_key(api_key: str) -> str:
    last = "A" if api_key[-1] != "A" else "B"
    return api_key[:-1] + last


def _run_authenticated_e2e(
    connection: http.client.HTTPSConnection,
    *,
    base_path: str,
    api_key: str,
    model: str,
) -> None:
    chat_path = f"{base_path}/chat/completions"
    # 1. Invalid key isolation check
    connection.request(
        "POST",
        chat_path,
        body=json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": "Synthetic probe."}],
            }
        ),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_tamper_key(api_key)}",
        },
    )
    response = connection.getresponse()
    response.read()
    if response.status not in (401, 403):
        raise SystemExit("tampered API key was not refused")

    # 2. Non-streaming E2E round-trip (rules + NER -> upstream -> vault restore)
    connection.request(
        "POST",
        chat_path,
        body=json.dumps(
            {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Write one short sentence to Jane Placeholder at "
                            "jane.placeholder@example.com confirming her request."
                        ),
                    }
                ],
                "stream": False,
                "max_completion_tokens": 1024,
            }
        ),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-PII-Guard-Echo": "masked",
        },
    )
    response = connection.getresponse()
    raw = response.read()
    if response.status != 200:
        raise SystemExit(f"authenticated non-streaming E2E failed with status {response.status}")
    payload = json.loads(raw)
    try:
        masked_prompt = payload["pii_guard"]["masked_messages"][0]["content"]
        restored_reply = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise SystemExit("authenticated non-streaming E2E returned unexpected schema") from None
    if (
        not isinstance(masked_prompt, str)
        or "Jane Placeholder" in masked_prompt
        or "jane.placeholder@example.com" in masked_prompt
    ):
        raise SystemExit("authenticated E2E leaked synthetic PII in masked prompt")
    found_types = {match.group(1) for match in PLACEHOLDER_RE.finditer(masked_prompt)}
    if not {"PERSON", "EMAIL"} <= found_types:
        raise SystemExit("authenticated E2E did not mask both PERSON and EMAIL")
    if not isinstance(restored_reply, str) or not restored_reply.strip():
        raise SystemExit("authenticated E2E returned an empty reply")
    if PLACEHOLDER_RE.search(restored_reply):
        raise SystemExit("authenticated E2E left un-restored placeholders in reply")

    # 3. Streaming SSE E2E round-trip
    connection.request(
        "POST",
        chat_path,
        body=json.dumps(
            {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Repeat the email jane.placeholder@example.com verbatim in a "
                            "short confirmation to Jane Placeholder."
                        ),
                    }
                ],
                "stream": True,
                "max_completion_tokens": 1024,
            }
        ),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    response = connection.getresponse()
    stream_raw = response.read().decode("utf-8", errors="replace")
    if response.status != 200:
        raise SystemExit(f"authenticated streaming E2E failed with status {response.status}")
    chunks: list[str] = []
    saw_done = False
    for line in stream_raw.splitlines():
        if not line.startswith("data: "):
            continue
        data = line[6:].strip()
        if data == "[DONE]":
            saw_done = True
            break
        event = json.loads(data)
        for choice in event.get("choices") or []:
            delta = (choice.get("delta") or {}).get("content")
            if isinstance(delta, str):
                chunks.append(delta)
    streamed_reply = "".join(chunks)
    if not saw_done or not streamed_reply.strip():
        raise SystemExit("authenticated streaming E2E did not complete with content")
    if PLACEHOLDER_RE.search(streamed_reply):
        raise SystemExit("authenticated streaming E2E left un-restored placeholders")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="Canonical HTTPS origin (e.g. https://guard.watt-mind.com)")
    parser.add_argument(
        "--require-e2e",
        action="store_true",
        help=(
            "Run the paid E2E tiers: the sponsored demo round-trip and, with "
            "PII_GUARD_SMOKE_API_KEY set, authenticated chat. Never pass this from deploy.sh: "
            "those calls spend sponsored budget and a failure there must not roll back ingress"
        ),
    )
    parser.add_argument(
        "--endpoint-url",
        default=os.environ.get("PII_GUARD_SMOKE_ENDPOINT_URL", ""),
        help="Optional endpoint base URL or path (/e/<id>/v1) for the authenticated E2E",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    # The key comes only from the environment, never argv, so it stays out of ps and logs.
    api_key = os.environ.get("PII_GUARD_SMOKE_API_KEY", "")

    origin, canonical_origin = _parse_origin(args.origin)
    assert origin.hostname is not None  # noqa: S101 - verified by _parse_origin
    endpoint_path = _parse_endpoint_path(args.endpoint_url, canonical_origin)

    connection = http.client.HTTPSConnection(origin.hostname, origin.port or 443, timeout=60)
    try:
        # 1. Public landing & security headers
        connection.request("GET", "/")
        response = connection.getresponse()
        response.read()
        if response.status != 200:
            raise SystemExit("public landing failed")
        _check_security_headers(_response_headers(response))

        # 2. Bounded wait for full NER readiness (LAB-1548)
        deadline = time.monotonic() + READY_WAIT_SECONDS
        while True:
            connection.request("GET", "/readyz")
            response = connection.getresponse()
            response.read()
            if response.status == 200:
                break
            if response.status != 503 or time.monotonic() >= deadline:
                raise SystemExit("public readiness failed")
            time.sleep(5)

        # 3. Healthz NER state
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        health = json.loads(response.read())
        if response.status != 200 or health.get("ner") != "ready":
            raise SystemExit("required NER is not ready")

        # 4. Host-aware robots.txt
        _check_robots(connection, origin.hostname)

        # 5. Anonymous protected API refusal
        connection.request(
            "POST",
            "/v1/analyze",
            body=json.dumps({"text": "Synthetic specimen.", "language": "en"}),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
        if response.status not in (401, 403):
            raise SystemExit(
                "anonymous protected API was accepted or returned an unexpected status"
            )

        # 6. Identity-header spoofing refusal (caller-supplied X-MS-CLIENT-PRINCIPAL)
        connection.request(
            "POST",
            "/v1/analyze",
            body=json.dumps({"text": "Synthetic specimen.", "language": "en"}),
            headers={
                "Content-Type": "application/json",
                "Origin": canonical_origin,
                "X-MS-CLIENT-PRINCIPAL": SPOOFED_PRINCIPAL,
            },
        )
        response = connection.getresponse()
        response.read()
        if response.status not in (401, 403):
            raise SystemExit("spoofed X-MS-CLIENT-PRINCIPAL header was accepted on protected API")

        connection.request(
            "GET",
            "/v1/account",
            headers={"X-MS-CLIENT-PRINCIPAL": SPOOFED_PRINCIPAL},
        )
        response = connection.getresponse()
        account_headers = _response_headers(response)
        account_body = json.loads(response.read() or b"{}")
        if response.status != 200 or account_body.get("authenticated") is not False:
            raise SystemExit("spoofed X-MS-CLIENT-PRINCIPAL established an authenticated session")

        # 7. Cross-origin CSRF refusal on state/work POST
        guest_cookie = _extract_guest_cookie(account_headers)
        csrf_headers = {
            "Content-Type": "application/json",
            "Origin": "https://evil.example",
        }
        if guest_cookie:
            csrf_headers["Cookie"] = guest_cookie
        connection.request(
            "POST",
            "/v1/demo",
            body=json.dumps({"sample_id": "en-support"}),
            headers=csrf_headers,
        )
        response = connection.getresponse()
        csrf_payload = json.loads(response.read() or b"{}")
        csrf_code = (csrf_payload.get("error") or {}).get("code")
        if response.status != 403 or csrf_code != "hosted_request_denied":
            raise SystemExit("cross-origin POST /v1/demo was not refused with 403")

        # 8. Public walkthrough E2E (/v1/demo) or zero-sponsorship refusal check
        limits = account_body.get("limits")
        sponsored_enabled = limits.get("sponsored_enabled") if isinstance(limits, dict) else None
        if args.require_e2e and sponsored_enabled is not True:
            raise SystemExit("sponsored E2E was required but sponsored_enabled is not true")

        demo_headers = {
            "Content-Type": "application/json",
            "Origin": canonical_origin,
        }
        if guest_cookie:
            demo_headers["Cookie"] = guest_cookie
        if sponsored_enabled is True and not args.require_e2e:
            # A live demo spends sponsored budget; the release gate stays free and read-only.
            demo_summary = "sponsored demo E2E skipped (pass --require-e2e)"
        else:
            connection.request(
                "POST",
                "/v1/demo",
                body=json.dumps({"sample_id": "en-support"}),
                headers=demo_headers,
            )
            response = connection.getresponse()
            demo_payload = json.loads(response.read() or b"{}")
            if args.require_e2e:
                if response.status != 200:
                    raise SystemExit(f"public demo E2E failed with status {response.status}")
                _check_demo_roundtrip(demo_payload)
                demo_summary = "public demo E2E round-trip passed"
            else:
                error_code = (demo_payload.get("error") or {}).get("code")
                if response.status != 503 or error_code != "sponsored_unavailable":
                    raise SystemExit(
                        "zero-sponsorship /v1/demo did not fail closed with 503 "
                        "sponsored_unavailable"
                    )
                demo_summary = "zero-sponsorship refusal verified"

        # 9. Optional authenticated non-streaming + streaming E2E
        auth_summary = "set PII_GUARD_SMOKE_API_KEY with --require-e2e for authenticated E2E"
        if api_key and args.require_e2e:
            model = account_body.get("included_model") or "muse-spark-1.3"
            _run_authenticated_e2e(
                connection,
                base_path=endpoint_path,
                api_key=api_key,
                model=model,
            )
            auth_summary = (
                f"authenticated non-streaming + SSE streaming E2E passed ({endpoint_path})"
            )
    finally:
        connection.close()

    print(
        "Smoke passed: landing, security headers, robots.txt, readiness, anonymous/spoofed-header "
        f"refusal, CSRF refusal, {demo_summary}; {auth_summary}."
    )


if __name__ == "__main__":
    main()
