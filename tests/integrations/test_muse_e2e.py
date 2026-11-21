"""A real, pinned Muse Code works on the fictional mini-repo through the gateway's Responses
API front end (scripted upstream).

Muse Code ``MUSE_VERSION_CHECKED`` comes from its release manifest (size and sha256 checked)
into a throwaway ``HOME`` (~450 MB): set ``PII_GUARD_MUSE_HOME`` to reuse an install across
runs, ``PII_GUARD_MUSE_VERSION`` to run another version. Whatever the official installer serves
today does not matter here: a new upstream release is reported by the nightly ``muse-drift``
job (``scripts/ci/muse_drift.py``, LAB-2433). Skipped when the release can't be fetched
(offline); a manifest or download that doesn't match the pin **fails**. The live variant against
the Meta Model API is ``python -m pii_guard.integrations.e2e --client muse-code --upstream ...``
(docs/integrations/muse-code.md).
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from pii_guard.integrations import e2e
from pii_guard.integrations.e2e import (
    MUSE_VERSION,
    MuseIntegrityError,
    install_muse,
    load_gold,
    muse_platform,
    run_muse,
)

needs_bash = pytest.mark.skipif(
    shutil.which("bash") is None or platform.system() not in ("Darwin", "Linux"),
    reason="Muse Code runs on macOS and Linux",
)
VERSION = os.environ.get("PII_GUARD_MUSE_VERSION") or MUSE_VERSION


@pytest.fixture(scope="module")
def muse_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    home = os.environ.get("PII_GUARD_MUSE_HOME")
    path = Path(home) if home else tmp_path_factory.mktemp("muse-home")
    try:
        return install_muse(path, VERSION)
    except MuseIntegrityError as exc:
        pytest.fail(str(exc), pytrace=False)
    except (OSError, httpx.HTTPError, RuntimeError) as exc:
        pytest.skip(f"could not install Muse Code {VERSION} ({type(exc).__name__}: {exc})")


@needs_bash
def test_muse_code_through_gateway_masks_upstream_and_restores_files(muse_bin: Path) -> None:
    result = run_muse(muse_bin=muse_bin, timeout=300, version=VERSION)
    assert result.client_exit == 0, result.client_output
    # Main turns (read, read, read, write, answer) plus Muse's reminder observers.
    assert result.requests >= 5
    assert result.refused == 0, result.gateway_statuses  # the allow-list covers Muse's fields
    assert result.gold_upstream == []
    assert result.placeholders_upstream > 0
    assert result.files_written == ["reply.md"]
    # write_file arguments came back restored: the file holds the real (fictional) values.
    assert sorted(result.restored_in_files) == sorted(result.gold_checked)
    assert result.placeholders_in_files == 0
    assert set(load_gold()["rules"]) <= set(result.gold_checked)
    assert {"function_call", "function_call_output", "reasoning"} <= set(
        result.request_keys["input_items"]
    )
    # The connect path URL: one vault session, each value one placeholder (LAB-1286).
    assert result.session_sources == {"path": result.requests}
    assert result.sessions == 1
    assert result.gold_unstable == 0
    assert result.ok


@needs_bash
def test_muse_code_without_the_session_path_uses_prompt_cache_key(muse_bin: Path) -> None:
    """The plain base URL: the session comes from prompt_cache_key. Muse sends one key for the
    main conversation and one per reminder observer; the observers' keys follow the main
    conversation's session (LAB-1300), so the task stays in one session, as with the path."""
    result = run_muse(muse_bin=muse_bin, timeout=300, session="auto", version=VERSION)
    assert result.client_exit == 0, result.client_output
    assert result.gold_upstream == []
    assert result.session_sources == {"prompt_cache_key": result.requests}
    assert result.sessions == 1
    assert result.gold_unstable == 0
    assert result.gold_max_placeholders == 1
    assert result.placeholders_in_files == 0
    assert result.ok


# --- the pinned install, offline (no download) -------------------------------------------

BUILD = b"\x7fELF a fake Muse Code build"
ARTIFACT_URL = "https://lookaside.example.test/muse-x86-linux"


def _manifest(version: str = MUSE_VERSION, **artifact: Any) -> dict[str, Any]:
    entry = {"url": ARTIFACT_URL, "checksum": hashlib.sha256(BUILD).hexdigest(), "size": len(BUILD)}
    return {
        "version": version,
        "checksum_algorithm": "sha256",
        "artifacts": {"x86_linux": {**entry, **artifact}, "aarch64_macos": dict(entry)},
    }


class _Release:
    """Stands in for the release manifest and the build it points at."""

    def __init__(self, manifest: Any, body: bytes = BUILD, status: int = 200) -> None:
        self.manifest = manifest
        self.body = body
        self.status = status
        self.manifests: list[str] = []
        self.downloads: list[str] = []

    def get(self, url: str, **_: Any) -> httpx.Response:
        self.manifests.append(url)
        return httpx.Response(self.status, json=self.manifest, request=httpx.Request("GET", url))

    @contextmanager
    def stream(self, method: str, url: str, **_: Any) -> Iterator[httpx.Response]:
        self.downloads.append(url)
        chunks = [self.body[i : i + 7] for i in range(0, len(self.body), 7)]
        yield httpx.Response(200, content=iter(chunks), request=httpx.Request(method, url))


@pytest.fixture
def release(monkeypatch: pytest.MonkeyPatch) -> Any:
    def make(manifest: Any = None, body: bytes = BUILD, status: int = 200) -> _Release:
        fake = _Release(_manifest() if manifest is None else manifest, body, status)
        monkeypatch.setattr(e2e.httpx, "get", fake.get)
        monkeypatch.setattr(e2e.httpx, "stream", fake.stream)
        monkeypatch.setattr(e2e, "muse_platform", lambda: "x86_linux")
        return fake

    return make


def test_the_pin_is_installed_from_its_release_manifest_and_reused(
    release: Any, tmp_path: Path
) -> None:
    fake = release()
    binary = install_muse(tmp_path)
    assert binary == tmp_path / ".local" / "bin" / f"muse-bin-{MUSE_VERSION}"
    assert binary.read_bytes() == BUILD
    assert binary.stat().st_mode & stat.S_IXUSR
    assert fake.manifests == [e2e.MUSE_MANIFEST.format(version=MUSE_VERSION)]
    assert f"version={MUSE_VERSION}&" in fake.manifests[0]
    assert fake.downloads == [ARTIFACT_URL]
    assert install_muse(tmp_path) == binary
    assert len(fake.manifests) == 1  # the second call reuses the install
    assert [p.name for p in binary.parent.iterdir()] == [binary.name]  # no partial left


def test_another_version_comes_from_its_own_manifest(release: Any, tmp_path: Path) -> None:
    fake = release(_manifest("9.9.9-R1.1"))
    assert install_muse(tmp_path, "9.9.9-R1.1").name == "muse-bin-9.9.9-R1.1"
    assert fake.manifests == [e2e.MUSE_MANIFEST.format(version="9.9.9-R1.1")]


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (BUILD[:-1] + b"!", "sha256"),
        (BUILD[:-3], f"expected {len(BUILD)} bytes"),
        (BUILD + b"tail", "had more"),
    ],
    ids=["checksum", "short", "long"],
)
def test_a_download_that_does_not_match_fails_and_leaves_nothing(
    release: Any, tmp_path: Path, body: bytes, match: str
) -> None:
    release(body=body)
    with pytest.raises(MuseIntegrityError, match=match):
        install_muse(tmp_path)
    assert list((tmp_path / ".local" / "bin").iterdir()) == []


@pytest.mark.parametrize(
    "manifest",
    [
        _manifest("1.0.0-R1.1"),  # another version than asked for
        {**_manifest(), "checksum_algorithm": "md5"},
        {**_manifest(), "artifacts": {"aarch64_macos": _manifest()["artifacts"]["aarch64_macos"]}},
        _manifest(url="http://lookaside.example.test/muse"),
        _manifest(checksum="not-a-sha256"),
        _manifest(size=0),
        _manifest(size=True),
        ["not", "a", "manifest"],
    ],
    ids=["version", "algorithm", "platform", "http", "checksum", "size", "bool-size", "list"],
)
def test_a_manifest_that_does_not_match_the_pin_fails(
    release: Any, tmp_path: Path, manifest: Any
) -> None:
    fake = release(manifest)
    with pytest.raises(MuseIntegrityError):
        install_muse(tmp_path)
    assert fake.downloads == []


def test_an_unreachable_manifest_is_an_http_error_not_an_integrity_error(
    release: Any, tmp_path: Path
) -> None:
    release(status=404)
    with pytest.raises(httpx.HTTPStatusError):
        install_muse(tmp_path)


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Linux", "x86_64", "x86_linux"),
        ("Linux", "aarch64", "aarch64_linux"),
        ("Darwin", "arm64", "aarch64_macos"),
        ("Darwin", "x86_64", "x86_macos"),
    ],
)
def test_the_platform_maps_like_the_launcher(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str, expected: str
) -> None:
    monkeypatch.setattr(e2e.platform, "system", lambda: system)
    monkeypatch.setattr(e2e.platform, "machine", lambda: machine)
    assert muse_platform() == expected


def test_an_unsupported_platform_is_not_an_integrity_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(e2e.platform, "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="no build") as caught:
        muse_platform()
    assert not isinstance(caught.value, MuseIntegrityError)


def test_the_cli_stops_on_a_manifest_mismatch(
    release: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release(body=b"tampered")
    with pytest.raises(SystemExit) as caught:
        e2e.main(["--client", "muse-code", "--muse-home", str(tmp_path)])
    assert caught.value.code == 2
    assert f"expected {len(BUILD)} bytes" in capsys.readouterr().err
