"""Detector registry: maps short names (``"rules"``) to lazily imported detector classes.

Names resolve in this order:

1. explicit registrations (built-ins below, or :func:`register_detector` at runtime);
2. the ``pii_guard.detectors`` entry-point group, for third-party packages;
3. the module convention ``pii_guard.detect.<name>``, which must define
   ``DETECTOR_CLASS`` (the detector class).

So a new built-in detector only has to add ``src/pii_guard/detect/<name>.py`` with
``DETECTOR_CLASS = MyDetector``; no shared file needs editing. Nothing is imported until a
name is resolved, so heavy model dependencies stay off the import path of the CLI and API.
"""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import Any

from pii_guard.types import DetectionError, Detector

__all__ = [
    "ENTRY_POINT_GROUP",
    "create_detector",
    "detector_names",
    "register_detector",
    "resolve_detector",
]

ENTRY_POINT_GROUP = "pii_guard.detectors"

_BUILTIN: dict[str, str] = {
    "rules": "pii_guard.detect.rules:RuleDetector",
}
_registry: dict[str, str] = dict(_BUILTIN)


def register_detector(name: str, target: str, *, replace: bool = False) -> None:
    """Register ``name`` -> ``"package.module:ClassName"``. Nothing is imported yet."""
    if ":" not in target:
        raise ValueError(f"target must look like 'package.module:ClassName', got {target!r}")
    if name in _registry and _registry[name] != target and not replace:
        raise ValueError(f"detector {name!r} is already registered as {_registry[name]!r}")
    _registry[name] = target


def detector_names() -> list[str]:
    """Explicitly registered and entry-point detector names (convention names not listed)."""
    names = set(_registry)
    names.update(ep.name for ep in entry_points(group=ENTRY_POINT_GROUP))
    return sorted(names)


def _import_target(name: str, target: str) -> type[Detector]:
    module_name, _, attr = target.partition(":")
    try:
        module = importlib.import_module(module_name)
        return getattr(module, attr)
    except (ImportError, AttributeError) as exc:
        raise DetectionError(f"detector {name!r} could not be loaded from {target!r}") from exc


def resolve_detector(name: str) -> type[Detector]:
    """Return the detector class for ``name``. Raises :class:`DetectionError` if unknown."""
    if name in _registry:
        return _import_target(name, _registry[name])

    for ep in entry_points(group=ENTRY_POINT_GROUP):
        if ep.name == name:
            try:
                return ep.load()
            except (ImportError, AttributeError) as exc:
                raise DetectionError(f"detector {name!r} entry point failed to load") from exc

    if name.isidentifier():
        module_name = f"pii_guard.detect.{name}"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name not in (module_name, "pii_guard.detect"):
                raise DetectionError(f"detector {name!r} failed to import") from exc
        else:
            cls = getattr(module, "DETECTOR_CLASS", None)
            if cls is not None:
                return cls
            raise DetectionError(f"module {module_name!r} does not define DETECTOR_CLASS")

    raise DetectionError(f"unknown detector {name!r}")


def create_detector(name: str, **kwargs: Any) -> Detector:
    """Resolve ``name`` and instantiate it with ``kwargs``."""
    cls = resolve_detector(name)
    return cls(**kwargs)
