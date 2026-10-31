"""Shared fixtures. All test data is synthetic (ADR 0005)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import starlette.testclient
from fastapi.testclient import TestClient
from hypothesis import settings as hypothesis_settings

from pii_guard.api.app import create_app
from pii_guard.config import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parent.parent

# Hypothesis profiles. No deadline anywhere: one rules pass over a long random string can take
# ~300 ms on a loaded machine, past the 200 ms default, which failed a full run once (LAB-1230).
# The CI profiles are also derandomized: the same examples on every run, so a red CI run
# reproduces locally with the same profile; a failure prints the reproduce blob. "ci" (pull
# requests, merge queue, develop) runs 25 examples where a test sets no max_examples of its own;
# "ci-full" (main, nightly, manual) runs Hypothesis's default 100 (LAB-1267, LAB-1446).
hypothesis_settings.register_profile("dev", deadline=None)
hypothesis_settings.register_profile(
    "ci", deadline=None, derandomize=True, print_blob=True, max_examples=25
)
hypothesis_settings.register_profile("ci-full", deadline=None, derandomize=True, print_blob=True)
hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


_CI_MAX_EXAMPLES = 25


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Shrink explicit Hypothesis example counts on the ``ci`` profile (LAB-1288).

    The ``ci`` profile's ``max_examples=25`` only reaches tests without their own
    ``@settings(max_examples=...)``; most property tests set 50 to 300 explicitly and ran
    at full size on pull requests. On ``ci`` this hook derives each collected test's
    settings with the count capped, so PR runs shrink them while ``dev`` and ``ci-full``
    (nightly, main) keep the full count. Derandomized either way: the same seed runs the
    same (fewer) examples, and a red run still prints the reproduce blob."""
    if os.environ.get("HYPOTHESIS_PROFILE") != "ci":
        return
    for item in items:
        fn = getattr(item, "obj", None)
        current = getattr(fn, "_hypothesis_internal_use_settings", None)
        if current is None:
            continue
        limit = current.max_examples
        if limit is not None and limit > _CI_MAX_EXAMPLES:
            fn._hypothesis_internal_use_settings = hypothesis_settings(
                current, max_examples=_CI_MAX_EXAMPLES
            )


def pytest_report_header() -> str:
    s = hypothesis_settings.default
    return f"hypothesis: derandomize={s.derandomize} deadline={s.deadline} (seed per test name)"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Isolate every test from the developer's environment and any local ``.env``."""
    for key in list(os.environ):
        if key.startswith("PII_GUARD_") or key == "META_API_KEY":
            monkeypatch.delenv(key, raising=False)
    # No NER model download from a test: an empty model cache, the fallback used only if cached
    # (so with torch/transformers installed, the default, the stack is still rules only; LAB-1192).
    monkeypatch.setenv("PII_GUARD_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("PII_GUARD_PROJECT_STATE_PATH", str(tmp_path / "projects" / "state.sqlite3"))
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "cached")
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# TestClient defaults to Host "testserver" from client "testclient": a non-loopback name the API
# refuses (DNS-rebinding guard, LAB-1203). Default to what a local client really sends; tests of
# the guards pass base_url/client/headers explicitly.
LOCAL_BASE_URL = "http://127.0.0.1:8787"
LOCAL_CLIENT = ("127.0.0.1", 50000)


@pytest.fixture(autouse=True)
def local_test_client(monkeypatch: pytest.MonkeyPatch) -> None:
    init = starlette.testclient.TestClient.__init__
    code, defaults = init.__code__, init.__defaults__ or ()
    names = code.co_varnames[code.co_argcount - len(defaults) : code.co_argcount]
    local = {"base_url": LOCAL_BASE_URL, "client": LOCAL_CLIENT}
    monkeypatch.setattr(
        init, "__defaults__", tuple(local.get(n, d) for n, d in zip(names, defaults, strict=True))
    )


NER_AUTODETECT = "ner_autodetect"
UNTRACED = "untraced"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{NER_AUTODETECT}: let build_mode_detectors add NER when torch/transformers import "
        "(by default the suite pins the gateway base detectors to rules only)",
    )
    config.addinivalue_line(
        "markers",
        f"{UNTRACED}: run the test body with coverage measurement stopped (LAB-1447); for "
        "checks of committed data or a whole corpus whose code other tests measure",
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    """Stop every running coverage measurement around an ``untraced`` test body.

    Under the branch tracer a pure-Python hot loop runs 7-16x slower. pytest-cov's own
    ``no_cover`` is not enough: in an xdist worker a second, automatically started
    ``Coverage`` keeps tracing, and with ``--no-cov`` it fails. Fixtures stay measured.
    """
    if item.get_closest_marker(UNTRACED) is None:
        return (yield)
    stopped = []
    try:
        import coverage
    except ImportError:  # pragma: no cover - coverage is a dev dependency
        pass
    else:
        while (cov := coverage.Coverage.current()) is not None and cov not in stopped:
            cov.stop()
            stopped.append(cov)
    try:
        return (yield)
    finally:
        for cov in reversed(stopped):
            cov.start()


@pytest.fixture(autouse=True)
def rules_only_mode_detectors(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make implicit ``build_mode_detectors`` calls independent of the installed extras.

    Without ``base=``, ``build_mode_detectors`` adds ``ner`` whenever torch and transformers
    import (the default install since LAB-1733) and a model is cached, so a developer's venv
    would see different spans, detector lists and system keys than CI. Tests get rules only
    unless they pass ``base=`` themselves or are marked
    ``@pytest.mark.ner_autodetect`` to keep the real, environment-dependent selection.
    """
    if request.node.get_closest_marker(NER_AUTODETECT) is None:
        # The shared stack (LAB-1270): pins the REST API's default detectors too.
        monkeypatch.setattr("pii_guard.detect.stack._ner_available", lambda: False)


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c
