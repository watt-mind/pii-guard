"""NER model loading is serialised process-wide and shared (LAB-1274).

Two NerDetector instances (the REST API's and the gateway's) loading and first running the
model at the same time crashed the API with signal 11 on Apple MPS. These tests use a fake
model: no torch, no weights.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.detect import ner, stack
from pii_guard.detect.ner import NerDetector, RawEntity
from pii_guard.types import DetectionError

CALLERS = 16
TEXT = "Teszt Elek"


class FakeModel:
    """Counts constructions; slow to build, so racing callers overlap inside the loader."""

    built = 0
    active = 0
    max_active = 0
    fail_next = False
    guard = threading.Lock()

    def __init__(self, model: str, **kwargs: Any) -> None:
        cls = type(self)
        with cls.guard:
            cls.active += 1
            cls.max_active = max(cls.max_active, cls.active)
        try:
            time.sleep(0.05)
            if cls.fail_next:
                cls.fail_next = False
                raise OSError("fictional load failure")
            self.model = model
            self.kwargs = kwargs
            self.ready = True  # set last: a published backend must be fully built
            with cls.guard:
                cls.built += 1
        finally:
            with cls.guard:
                cls.active -= 1

    def predict(self, text: str) -> list[RawEntity]:
        assert self.ready
        return [RawEntity("PER", 0, len(text), 0.9)]


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[FakeModel]]:
    FakeModel.built = FakeModel.active = FakeModel.max_active = 0
    FakeModel.fail_next = False
    monkeypatch.setattr(ner, "TransformersBackend", FakeModel)
    monkeypatch.setattr(ner, "dependencies_available", lambda: True)
    monkeypatch.setattr(ner, "_shared_backends", {})
    for name in ("PII_GUARD_NER_DEVICE", "PII_GUARD_NER_BACKEND", "PII_GUARD_NER_REVISION"):
        monkeypatch.delenv(name, raising=False)
    yield FakeModel


def _all_at_once(fn: Any, n: int = CALLERS) -> list[Any]:
    barrier = threading.Barrier(n)

    def call(i: int) -> Any:
        barrier.wait()
        return fn(i)

    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(call, range(n)))


def test_one_detector_loads_once_under_concurrent_first_calls() -> None:
    calls: list[int] = []

    def factory() -> Any:
        calls.append(1)
        time.sleep(0.05)
        return FakeModel("fictional-ner")

    detector = NerDetector(backend=factory, preload=False)
    results = _all_at_once(lambda _: detector.detect(TEXT))
    assert calls == [1]
    assert all(len(spans) == 1 for spans in results)


def test_detectors_with_the_same_model_share_one_load(fake_model: type[FakeModel]) -> None:
    detectors = [
        NerDetector(model="./models/fictional-ner", device="cpu", preload=False)
        for _ in range(CALLERS)
    ]
    backends = _all_at_once(lambda i: detectors[i].load())
    assert fake_model.built == 1
    assert fake_model.max_active == 1
    assert all(b is backends[0] for b in backends)
    assert all(len(d.detect(TEXT)) == 1 for d in detectors)


def test_loads_are_serialised_across_models(fake_model: type[FakeModel]) -> None:
    detectors = [
        NerDetector(model=f"./models/fictional-ner-{i}", device="cpu", preload=False)
        for i in range(4)
    ]
    backends = _all_at_once(lambda i: detectors[i % 4].load(), n=8)
    assert fake_model.built == 4
    assert fake_model.max_active == 1  # never two loads at once, even for different models
    assert len({id(b) for b in backends}) == 4


def test_a_different_configuration_gets_its_own_backend(fake_model: type[FakeModel]) -> None:
    a = NerDetector(model="./models/fictional-ner", device="cpu")
    b = NerDetector(model="./models/fictional-ner", device="cpu", max_length=256)
    c = NerDetector(model="./models/fictional-ner", device="cpu")
    assert a.load() is not b.load()
    assert a.load() is c.load()
    assert fake_model.built == 2


def test_a_failed_load_is_not_shared_and_is_retried(fake_model: type[FakeModel]) -> None:
    fake_model.fail_next = True
    detector = NerDetector(model="./models/fictional-ner", device="cpu", preload=False)
    with pytest.raises(DetectionError, match=r"could not be loaded \(OSError\)"):
        detector.load()
    assert ner._shared_backends == {}
    assert len(detector.detect(TEXT)) == 1
    assert fake_model.built == 1


def test_warm_up_loads_the_configured_model(
    fake_model: type[FakeModel], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stack, "_ner_available", lambda: True)
    settings = Settings(ner_model="./models/fictional-ner", ner_device="cpu")
    assert stack.warm_up(settings) is True
    assert fake_model.built == 1
    # The REST API's and the gateway's detectors then reuse it.
    stack.build_detectors(["rules", "ner"], settings)
    stack.build_detectors(["ner"], settings)
    assert fake_model.built == 1


def test_warm_up_is_a_no_op_without_a_configured_model(
    fake_model: type[FakeModel], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stack, "_ner_available", lambda: True)
    assert stack.warm_up(Settings()) is False
    monkeypatch.setattr(stack, "_ner_available", lambda: False)
    assert stack.warm_up(Settings(ner_model="./models/fictional-ner")) is False
    assert fake_model.built == 0


def test_app_warms_ner_before_serving(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Settings] = []

    def warm_up(settings: Settings) -> bool:
        calls.append(settings)
        return True

    monkeypatch.setattr(stack, "warm_up", warm_up)
    settings = Settings(detectors=("rules",))
    app = create_app(settings)
    assert calls == []
    with TestClient(app) as client:
        assert calls == [settings]
        assert client.get("/healthz").status_code == 200


def test_app_startup_fails_closed_when_warm_up_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def warm_up(settings: Settings) -> bool:
        raise DetectionError("ner model could not be loaded (OSError)")

    monkeypatch.setattr(stack, "warm_up", warm_up)
    app = create_app(Settings(detectors=("rules",)))
    with pytest.raises(DetectionError), TestClient(app):
        pass
