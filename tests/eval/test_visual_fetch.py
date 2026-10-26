"""The specimen fetcher: politeness rules and manifest, on a mocked network (no real hosts)."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from pii_guard.eval import visual_fetch
from pii_guard.eval.visual_fetch import (
    USER_AGENT,
    Blocked,
    PoliteFetcher,
    RateLimiter,
    fetch_catalog,
    parse_commons_file_page,
)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 5), (200, 10, 10)).save(buf, format="PNG")
    return buf.getvalue()


IMAGE = _png()
UPLOAD = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Card.png"


def _page(description: str, chrome: str = "Use this sample text in your project") -> str:
    return (
        f"<html><body><p>{chrome}</p>"
        f'<div class="fullImageLink" id="file"><a href="{UPLOAD}">img</a></div>'
        f'<table><tr><td class="description">{description}</td></tr></table>'
        '<span class="licensetpl_short">CC BY-SA 4.0</span>'
        '<div id="catlinks"><a>Identity cards</a></div></body></html>'
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _fetcher(handler, clock: FakeClock | None = None) -> PoliteFetcher:
    clock = clock or FakeClock()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PoliteFetcher(client, RateLimiter(1.0, clock=clock.clock, sleep=clock.sleep))


def test_rate_limiter_enforces_one_request_per_second() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock.clock, sleep=clock.sleep)
    for _ in range(4):
        limiter.wait()
    assert clock.sleeps == [1.0, 1.0, 1.0]
    with pytest.raises(ValueError):
        RateLimiter(0.5)


def test_robots_disallow_blocks_without_fetching_the_page() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.headers["user-agent"] == USER_AGENT
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, text="page")

    fetcher = _fetcher(handler)
    with pytest.raises(Blocked, match="disallows"):
        fetcher.get("https://example.test/az-eszemelyi/")
    assert seen == ["/robots.txt"]


@pytest.mark.parametrize(
    ("status", "body", "headers"),
    [
        (403, "challenge", {}),
        (200, "<!DOCTYPE html><title>Browser check</title>", {"content-type": "text/html"}),
    ],
)
def test_an_access_wall_on_robots_means_disallow_all(status, body, headers) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(status, text=body, headers=headers)
        raise AssertionError("must not fetch past a refused robots.txt")

    with pytest.raises(Blocked, match="access wall"):
        _fetcher(handler).get("https://example.test/prado/en/list.html")


def test_missing_robots_allows_and_403_on_the_page_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(403)

    with pytest.raises(Blocked, match="HTTP 403"):
        _fetcher(handler).get("https://example.test/page")


def test_specimen_marker_only_counts_description_categories_and_title() -> None:
    plain = parse_commons_file_page(_page("Hungarian ID"), "File:HunID.jpg")
    assert plain.original_url == UPLOAD
    assert plain.licence == "CC BY-SA 4.0"
    assert plain.is_specimen is False  # "sample" in the page chrome does not count
    marked = parse_commons_file_page(_page("Official specimen of the card"), "File:x.jpg")
    assert marked.is_specimen is True
    assert parse_commons_file_page(_page("card"), "File:Dowod-wzorzec.png").is_specimen
    with pytest.raises(ValueError):
        parse_commons_file_page("<html></html>", "File:x.jpg")


def _commons_handler(description: str, counter: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(f"{request.url.host}{request.url.path}")
        if request.url.path == "/robots.txt":
            if request.url.host == "blocked.test":
                return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
            return httpx.Response(200, text="User-agent: *\nDisallow: /w/\n")
        if request.url.host == "commons.wikimedia.org":
            return httpx.Response(200, text=_page(description))
        if request.url.host == "upload.wikimedia.org":
            return httpx.Response(200, content=IMAGE, headers={"content-type": "image/png"})
        return httpx.Response(404)

    return handler


def _catalog(**extra) -> dict:
    entry = {"country": "HU", "doc_type": "id_card", "side": "front"}
    entry.update(commons_title="File:Card.png", **extra)
    return {
        "sources": [
            {"name": "probe", "url": "https://blocked.test/list.html", "kind": "probe"},
            {"name": "commons", "url": "https://commons.wikimedia.org/", "kind": "commons"},
        ],
        "specimens": [entry],
    }


def test_fetch_catalog_downloads_into_out_dir_and_writes_hashes(tmp_path: Path) -> None:
    calls: list[str] = []
    fetcher = _fetcher(_commons_handler("Specimen ID card", calls))
    manifest = fetch_catalog(_catalog(), tmp_path / "specimens", fetcher)

    assert manifest["sources"][0]["status"].startswith("blocked")
    assert manifest["sources"][1]["status"] == "used"
    [item] = manifest["specimens"]
    assert item["sha256"] == hashlib.sha256(IMAGE).hexdigest()
    assert item["licence"] == "CC BY-SA 4.0"
    assert item["specimen_evidence"] == "marked"
    assert item["url"] == UPLOAD
    assert (tmp_path / "specimens" / item["file"]).read_bytes() == IMAGE
    assert item["id"].startswith("hu-id-card-front-")
    # Never a value or an image in the manifest itself: it serialises to plain metadata.
    assert "base64" not in json.dumps(manifest)
    assert fetcher.requests == len(calls)


def test_unmarked_images_are_skipped_unless_reviewed(tmp_path: Path) -> None:
    calls: list[str] = []
    skipped = fetch_catalog(_catalog(), tmp_path, _fetcher(_commons_handler("ID card", calls)))
    assert skipped["specimens"] == []
    assert "specimen" in skipped["skipped"][0]["reason"]
    assert not any(host.startswith("upload") for host in calls)

    reviewed = fetch_catalog(
        _catalog(verified_specimen=True), tmp_path, _fetcher(_commons_handler("ID card", []))
    )
    assert reviewed["specimens"][0]["specimen_evidence"] == "reviewed"


def test_previous_downloads_are_reused(tmp_path: Path) -> None:
    first = fetch_catalog(_catalog(), tmp_path, _fetcher(_commons_handler("Specimen", [])))
    catalog = _catalog()
    catalog["previous"] = first["specimens"]
    calls: list[str] = []
    again = fetch_catalog(catalog, tmp_path, _fetcher(_commons_handler("Specimen", calls)))
    assert again["specimens"][0]["sha256"] == first["specimens"][0]["sha256"]
    assert not any("commons" in c or "upload" in c for c in calls)


def test_catalog_size_is_bounded(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["specimens"] = catalog["specimens"] * (visual_fetch.MAX_SPECIMENS + 1)
    with pytest.raises(ValueError, match="bound"):
        fetch_catalog(catalog, tmp_path, _fetcher(_commons_handler("Specimen", [])))


def test_main_writes_the_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(_catalog()), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    transport = httpx.MockTransport(_commons_handler("Specimen", []))
    args = ["--catalog", str(catalog_path), "--out", str(tmp_path / "out")]
    args += ["--manifest", str(manifest_path), "--interval", "1"]
    # Real sleeps would make this slow; the limiter is covered above.
    monkeypatch.setattr(visual_fetch.RateLimiter, "wait", lambda self: None)
    assert visual_fetch.main(args, transport=transport) == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["specimens"]) == 1
