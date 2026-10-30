"""Polite fetcher for official specimen ID documents (visual eval, ``eval/visual/``).

Specimen images are realistic, multilingual test material, but their licence status varies
and their photos show real specimen models, so per ADR 0005 they are **never committed**:
this module downloads them into a gitignored directory (default ``data/specimens/``) and
writes a manifest of where each came from (source URL, country, document type, retrieval
date, SHA-256). Only the catalog (what to fetch) and the manifest (URLs + hashes) are
committed.

Politeness rules, enforced here and covered by tests:

- an identifying ``User-Agent`` on every request;
- at most one request per second (:class:`RateLimiter`, shared by every host);
- ``robots.txt`` is read once per host and honoured; a ``401``/``403`` on ``robots.txt``
  (an access wall, e.g. a bot challenge) means *disallow everything*, as in
  :mod:`urllib.robotparser`. Nothing tries to get around a refusal: a blocked source is
  recorded in the manifest with the reason and skipped.

The catalog (``eval/visual/catalog.json``) names *probe* sources (checked and reported, e.g.
the EU PRADO register) and Wikimedia Commons files (fetched). For a Commons file, the file
description page is read to find the original upload URL and the licence. Its description,
categories or title must mark the image as a specimen/sample (see :data:`SPECIMEN_MARKERS`),
or the catalog entry must carry ``verified_specimen`` (a maintainer looked at the image and
confirmed it is an official specimen with a fictional holder); otherwise it is skipped.

```
uv run python eval/visual/fetch_specimens.py [--out data/specimens] [--manifest PATH]
```
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.robotparser import RobotFileParser

import httpx

from pii_guard.eval.data_dirs import SPECIMENS_DIR_ENV_VAR, specimens_dir

__all__ = [
    "DEFAULT_CATALOG",
    "DEFAULT_MANIFEST",
    "DEFAULT_OUT",
    "SPECIMEN_MARKERS",
    "USER_AGENT",
    "PoliteFetcher",
    "RateLimiter",
    "fetch_catalog",
    "main",
    "parse_commons_file_page",
]

USER_AGENT = "pii-guard-specimen-eval/0.1 (+https://github.com/watt-mind/pii-guard)"
DEFAULT_CATALOG = Path("eval/visual/catalog.json")
DEFAULT_MANIFEST = Path("eval/visual/manifest.json")
DEFAULT_OUT = Path("data/specimens")
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_SPECIMENS = 150

#: A Commons file page must contain one of these (case-insensitive) to count as a specimen:
#: the word in the document's own languages, or a well-known specimen holder name.
SPECIMEN_MARKERS: tuple[str, ...] = (
    "specimen",
    "spécimen",
    "sample",
    "muster",
    "mustermann",
    "musterfrau",
    "minta",
    "wzór",
    "wzorzec",
    "esemplare",
    "facsimile",
    "fac-simile",
    "modelo",
    "näidis",
    "malli",
    "paraugs",
    "pavyzdys",
    "vzor",
    "vzorec",
    "uzorak",
    "voorbeeld",
    "exemplar",
    "δείγμα",
    "образец",
)

_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class RateLimiter:
    """At most one request per ``interval`` seconds (shared across hosts)."""

    def __init__(
        self,
        interval: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if interval < 1.0:
            raise ValueError("politeness: the interval must be at least 1 second")
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            delay = self._last + self.interval - now
            if delay > 0:
                self._sleep(delay)
                now += delay
        self._last = now


class _Robots(RobotFileParser):
    """A robots.txt parser whose all/nothing flags are declared for the type checker.

    ``RobotFileParser`` sets ``allow_all`` / ``disallow_all`` in ``__init__`` and ``read()``
    sets them from the status code, but typeshed leaves them out; we set them ourselves
    because the fetch goes through our own client and rate limiter.
    """

    allow_all: bool
    disallow_all: bool


class Blocked(Exception):
    """A request that robots.txt or the server refused. The message is the reason."""


@dataclass
class PoliteFetcher:
    """GET with an identifying UA, the rate limit and robots.txt."""

    client: httpx.Client
    limiter: RateLimiter = field(default_factory=RateLimiter)
    user_agent: str = USER_AGENT
    requests: int = 0
    _robots: dict[str, _Robots] = field(default_factory=dict)

    def _get(self, url: str) -> httpx.Response:
        self.limiter.wait()
        self.requests += 1
        return self.client.get(url, headers={"User-Agent": self.user_agent}, timeout=60.0)

    def robots(self, url: str) -> _Robots:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(origin)
        if parser is not None:
            return parser
        parser = _Robots(origin + "/robots.txt")
        try:
            response = self._get(origin + "/robots.txt")
        except httpx.HTTPError:
            parser.disallow_all = True  # unknown: be conservative
        else:
            if response.status_code in (401, 403):
                parser.disallow_all = True
            elif 400 <= response.status_code < 500:
                parser.allow_all = True
            elif response.status_code >= 500:
                parser.disallow_all = True
            elif _looks_like_html(response):
                # A challenge or error page instead of a robots file: treat as a refusal.
                parser.disallow_all = True
            else:
                parser.parse(response.text.splitlines())
        self._robots[origin] = parser
        return parser

    def get(self, url: str) -> httpx.Response:
        """GET ``url`` or raise :class:`Blocked` (robots, 401/403/429, a bot challenge)."""
        parser = self.robots(url)
        if not parser.can_fetch(self.user_agent, url):
            reason = "robots.txt unreachable (access wall)" if parser.disallow_all else ""
            raise Blocked(reason or "robots.txt disallows this path")
        response = self._get(url)
        if response.status_code in (401, 403, 429):
            raise Blocked(f"HTTP {response.status_code} (automated access refused)")
        response.raise_for_status()
        return response


def _looks_like_html(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    return "html" in content_type or response.text.lstrip()[:15].lower().startswith("<!doctype")


@dataclass(frozen=True, slots=True)
class CommonsFile:
    original_url: str
    licence: str | None
    is_specimen: bool


_ORIGINAL_RE = re.compile(
    r'<div class="fullImageLink"[^>]*>\s*<a href="(?P<url>https://upload\.wikimedia\.org/[^"]+)"'
)
_ORIGINAL_FALLBACK_RE = re.compile(
    r'href="(?P<url>https://upload\.wikimedia\.org/wikipedia/commons/[0-9a-f]/[0-9a-f]{2}/[^"]+)"'
)
_LICENCE_RE = re.compile(r'<span class="licensetpl_short"[^>]*>(?P<lic>[^<]+)</span>')
_TAG_RE = re.compile(r"<[^>]+>")
_DESCRIPTION_RE = re.compile(r'<td class="description"[^>]*>(?P<body>.*?)</td>', re.S)
_CATLINKS_RE = re.compile(r'<div id="catlinks"(?P<body>.{0,4000})', re.S)


def parse_commons_file_page(page: str, title: str) -> CommonsFile:
    """Extract the original upload URL, the short licence and the specimen marker."""
    match = _ORIGINAL_RE.search(page) or _ORIGINAL_FALLBACK_RE.search(page)
    if match is None:
        raise ValueError("no original file link on the description page")
    licence_match = _LICENCE_RE.search(page)
    licence = html.unescape(licence_match.group("lic")).strip() if licence_match else None
    # Only the file's own description, its categories and its title count: the page chrome
    # contains words like "sample" on every page.
    parts = [m.group("body") for m in _DESCRIPTION_RE.finditer(page)]
    parts += [m.group("body") for m in _CATLINKS_RE.finditer(page)]
    parts.append(title.replace("_", " "))
    text = html.unescape(_TAG_RE.sub(" ", " ".join(parts))).lower()
    is_specimen = any(marker in text for marker in SPECIMEN_MARKERS)
    return CommonsFile(html.unescape(match.group("url")), licence, is_specimen)


def _slug(entry: dict[str, Any]) -> str:
    """A stable id: country, type, side and a short hash of the source title."""
    digest = hashlib.sha1(
        entry["commons_title"].encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:6]
    kind = entry["doc_type"].replace("_", "-")
    return f"{entry['country'].lower()}-{kind}-{entry['side'].replace('_', '-')}-{digest}"


def _commons_page_url(title: str) -> str:
    return "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


def _image_extension(response: httpx.Response, url: str) -> str:
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type in _IMAGE_TYPES:
        return _IMAGE_TYPES[content_type]
    suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".webp"):
        return ".jpg" if suffix == ".jpeg" else suffix
    raise ValueError(f"not an image ({content_type or 'no content type'})")


def fetch_catalog(
    catalog: dict[str, Any],
    out_dir: Path,
    fetcher: PoliteFetcher,
    *,
    today: dt.date | None = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> dict[str, Any]:
    """Probe the catalog's sources, download its Commons specimens, return the manifest.

    Already-downloaded files whose SHA-256 matches a previous manifest entry are not fetched
    again (pass that manifest's entries in ``catalog['previous']``).
    """
    today = today or dt.date.today()
    entries = list(catalog.get("specimens", []))
    if len(entries) > MAX_SPECIMENS:
        raise ValueError(f"catalog lists {len(entries)} specimens; the bound is {MAX_SPECIMENS}")
    out_dir.mkdir(parents=True, exist_ok=True)
    previous = {p["commons_title"]: p for p in catalog.get("previous", []) if "sha256" in p}

    sources: list[dict[str, Any]] = []
    for source in catalog.get("sources", []):
        record = {"name": source["name"], "url": source["url"]}
        if source.get("kind") == "probe":
            try:
                fetcher.get(source["url"])
                record["status"] = "reachable (not scraped: no fetch rules defined)"
            except Blocked as exc:
                record["status"] = f"blocked: {exc}"
            except httpx.HTTPError as exc:
                record["status"] = f"error: {type(exc).__name__}"
            log(f"source {source['name']}: {record['status']}")
        else:
            record["status"] = "used"
        sources.append(record)

    specimens: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for entry in entries:
        title = entry["commons_title"]
        base = {k: entry[k] for k in ("country", "doc_type", "side")}
        base["id"] = _slug(entry)
        base["commons_title"] = title
        base["source_page"] = _commons_page_url(title)
        prior = previous.get(title)
        if prior is not None:
            path = out_dir / prior["file"]
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == prior["sha256"]:
                specimens.append({**prior, **base, "file": prior["file"]})
                continue
        try:
            page = fetcher.get(base["source_page"]).text
            info = parse_commons_file_page(page, title)
            if not info.is_specimen and not entry.get("verified_specimen"):
                skipped.append({**base, "reason": "description does not mark it as a specimen"})
                log(f"skip {base['id']}: not marked as a specimen")
                continue
            response = fetcher.get(info.original_url)
            data = response.content
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError("image too large")
            ext = _image_extension(response, info.original_url)
        except Blocked as exc:
            skipped.append({**base, "reason": f"blocked: {exc}"})
            log(f"skip {base['id']}: blocked")
            continue
        except (httpx.HTTPError, ValueError) as exc:
            skipped.append({**base, "reason": f"error: {type(exc).__name__}"})
            log(f"skip {base['id']}: {type(exc).__name__}")
            continue
        file_name = base["id"] + ext
        (out_dir / file_name).write_bytes(data)
        specimens.append(
            {
                **base,
                "url": info.original_url,
                "licence": info.licence,
                "specimen_evidence": "marked" if info.is_specimen else "reviewed",
                "retrieved": today.isoformat(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "file": file_name,
            }
        )
        log(f"ok {base['id']}")
    return {
        "version": 1,
        "user_agent": fetcher.user_agent,
        # A path outside the checkout (PII_GUARD_SPECIMENS_DIR) would put a home directory in
        # the committed manifest; record the setting's name instead.
        "out_dir": f"${SPECIMENS_DIR_ENV_VAR}" if out_dir.is_absolute() else str(out_dir),
        "sources": sources,
        "specimens": specimens,
        "skipped": skipped,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_specimens",
        description="Download official specimen ID documents into a gitignored directory.",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--out",
        type=Path,
        default=specimens_dir(),
        help="where the images go (default: PII_GUARD_SPECIMENS_DIR, else data/specimens)",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between requests")
    return parser


def main(argv: Sequence[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    if args.manifest.is_file():
        catalog["previous"] = json.loads(args.manifest.read_text(encoding="utf-8")).get(
            "specimens", []
        )
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        fetcher = PoliteFetcher(client, RateLimiter(args.interval))
        manifest = fetch_catalog(
            catalog, args.out, fetcher, log=lambda msg: print(msg, file=sys.stderr)
        )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(
        f"fetched {len(manifest['specimens'])}, skipped {len(manifest['skipped'])}, "
        f"{fetcher.requests} request(s)",
        file=sys.stderr,
    )
    return 0
