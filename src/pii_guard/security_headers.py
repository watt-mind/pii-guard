"""Browser security headers for the hosted app (LAB-1460).

The app sets them itself, once each, on every response: the dev router forwards only an
explicit header set and collapses repeated headers (LAB-1467), and router or ingress changes
need an operator redeploy. A header a route already set is left as it is, never repeated.

``Strict-Transport-Security`` is not here: the Azure Container Apps ingress already sends it,
and a second copy from the app would repeat it.

The Content-Security-Policy allows scripts and styles from the app's own origin only, plus the
inline ``<script>`` and ``<style>`` elements of the served page by their SHA-256 hash, computed
from the built ``index.html`` at startup: the theme script's text depends on the build
(``%VITE_PII_GUARD_HOSTED%``), so a hash committed by hand would go stale. No
``'unsafe-inline'`` and no ``'unsafe-eval'``.

``Referrer-Policy`` is ``same-origin``, not ``no-referrer``: under ``no-referrer`` the Fetch
standard serializes the ``Origin`` of a non-GET request as ``null`` (Chromium does it for form
posts), and the hosted API refuses a browser write whose ``Origin`` is not its own
(:class:`~pii_guard.hosted.middleware.HostedMiddleware`). ``same-origin`` still sends nothing
to another site.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterable
from html.parser import HTMLParser

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["SecurityHeadersMiddleware", "content_security_policy", "inline_hashes"]

#: FastAPI's API reference pages load Swagger UI / ReDoc from a CDN with inline scripts; they
#: keep the framing and plugin restrictions but not the script and style allowlist.
DOCS_PATHS = ("/docs", "/redoc")
DOCS_CSP = "frame-ancestors 'none'; object-src 'none'; base-uri 'none'"

#: Powerful features the UI never uses, switched off for the page and anything it embeds.
PERMISSIONS_POLICY = ", ".join(
    f"{feature}=()"
    for feature in (
        "camera",
        "microphone",
        "geolocation",
        "payment",
        "usb",
        "serial",
        "hid",
        "bluetooth",
        "midi",
        "display-capture",
        "browsing-topics",
    )
)


class _InlineCollector(HTMLParser):
    """The text of every inline ``<script>`` (no ``src``) and ``<style>`` element."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self.styles: list[str] = []
        self._open: tuple[list[str], list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and not any(name == "src" for name, _ in attrs):
            self._open = (self.scripts, [])
        elif tag == "style":
            self._open = (self.styles, [])

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open[1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._open is not None and tag in ("script", "style"):
            target, parts = self._open
            target.append("".join(parts))
            self._open = None


def _sha256(text: str) -> str:
    digest = base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")
    return f"'sha256-{digest}'"


def inline_hashes(page: str) -> tuple[list[str], list[str]]:
    """CSP hash sources for the page's inline scripts and inline styles, in page order."""
    collector = _InlineCollector()
    collector.feed(page)
    collector.close()
    scripts = list(dict.fromkeys(_sha256(s) for s in collector.scripts))
    styles = list(dict.fromkeys(_sha256(s) for s in collector.styles))
    return scripts, styles


def content_security_policy(page: str = "") -> str:
    """The policy for ``page`` (the served ``index.html``): same origin, plus its inline hashes."""
    scripts, styles = inline_hashes(page)
    directives = {
        "default-src": ["'self'"],
        "script-src": ["'self'", *scripts],
        "style-src": ["'self'", *styles],
        # Vite inlines small assets as data: URIs; the Images screen previews uploads as blob:.
        "img-src": ["'self'", "data:", "blob:"],
        "font-src": ["'self'", "data:"],
        "connect-src": ["'self'"],
        "media-src": ["'self'", "blob:"],
        "worker-src": ["'self'"],
        "manifest-src": ["'self'"],
        "object-src": ["'none'"],
        "base-uri": ["'none'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
    }
    return "; ".join(f"{name} {' '.join(values)}" for name, values in directives.items())


def security_headers(page: str = "") -> list[tuple[str, str]]:
    """Every header the middleware adds, lower-case names, for ``page``."""
    return [
        ("content-security-policy", content_security_policy(page)),
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "same-origin"),
        ("permissions-policy", PERMISSIONS_POLICY),
        ("cross-origin-opener-policy", "same-origin"),
    ]


class SecurityHeadersMiddleware:
    """Adds :func:`security_headers` to every HTTP response that does not already carry one."""

    def __init__(
        self, app: ASGIApp, page: str = "", docs_paths: Iterable[str] = DOCS_PATHS
    ) -> None:
        self.app = app
        self.docs_paths = tuple(docs_paths)
        self.headers = [
            (k.encode("latin-1"), v.encode("latin-1")) for k, v in security_headers(page)
        ]
        self.docs_headers = [
            (k, DOCS_CSP.encode("latin-1") if k == b"content-security-policy" else v)
            for k, v in self.headers
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        docs = any(path == p or path.startswith(p + "/") for p in self.docs_paths)
        extra = self.docs_headers if docs else self.headers

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers.extend((k, v) for k, v in extra if k not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
